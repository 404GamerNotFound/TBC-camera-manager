from __future__ import annotations

import asyncio
import hmac
import importlib
import json
import logging
from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import date, datetime
from time import monotonic as _monotonic
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, database, mqtt
from .ingress import IngressPathMiddleware
from .api_common import (
    api_auth_error,
)
from .app_updates import AppUpdateCheckError, fetch_latest_release, is_newer
from .camera_modules import (
    CameraCapability,
    get_camera_module,
    list_camera_modules,
    reload_camera_modules,
)
from .camera_modules.packages import (
    install_plugin_archive,
)
from .camera_modules.detections import DetectionDefinition
from .camera_modules.registry import UnknownCameraModuleError
from .channels import apply_channel_enabled_filter
from .cloud_modules import (
    CloudConnectionError,
    CloudVerificationRequired,
    list_cloud_module_registrations,
    reload_cloud_modules,
)
from .cloud_modules.packages import (
    install_plugin_archive as install_cloud_plugin_archive,
)
from .network_modules import (
    NetworkConnectionError,
    get_network_module,
    list_network_module_registrations,
    reload_network_modules,
)
from .network_modules.packages import (
    install_plugin_archive as install_network_plugin_archive,
)
from .network_modules.registry import UnknownNetworkModuleError
from .config import load_settings
from .debug_log import install_debug_log
from .documentation import (
    documentation_files as _documentation_files,
    render_documentation_markdown as _render_documentation_markdown,
    resolve_documentation_file as _resolve_documentation_file,
)
from .detection import factory as detection_factory
from .detection.classes import AUDIO_KEY_LABELS, DETECTION_KEY_LABELS, LOITERING_KEY_LABELS
from .detection import audio_factory as audio_detection_factory
from .detection.audio_supervisor import audio_detection_supervisor
from .detection.model_provisioning import ensure_audio_model, ensure_default_coral_model, ensure_default_model
from .detection.plugin_models import resolve_plugin_model
from .detection.recognition import (
    FACE_TRIGGER_DETECTION_KEYS,
    PLATE_TRIGGER_DETECTION_KEYS,
    ensure_face_models,
    ensure_plate_models,
    process_recognition,
)
from .detection.backend import Detection
from .detection.supervisor import detection_supervisor
from .health import run_health_checks
from .go2rtc import Go2rtcManager
from .live import LiveManager, redact_rtsp_credentials, stream_uri_for
from .maintenance import apply_cleanup
from .mcp_server import build_mcp_app
from .plugin_sources import (
    PluginSourceError,
    StandardPluginSource,
    fetch_latest_commit_sha,
    github_repositories_match,
    list_uninstalled_plugin_candidates,
    parse_github_repo_url,
    resolve_and_fetch_plugin,
)
from .plugin_requirements import (
    MissingPluginRequirements,
)
from .plugin_templates import (
    build_camera_plugin_template,
    build_cloud_plugin_template,
    build_design_theme_template,
    build_network_plugin_template,
)
from .notifications import notify_event
from .recording import ContinuousRecordingManager, RecordingManager
from .security import generate_csrf_token
from .snapshots import DashboardSnapshotManager
from .template_filters import tojson_html_safe
from .themes import UnknownThemeError, get_theme_registration, reload_themes
from .themes.packages import (
    install_theme_archive,
)

LOGGER = logging.getLogger(__name__)
SETTINGS = load_settings()
database.configure_encryption(SETTINGS.secret_key)
BASE_DIR = Path(__file__).resolve().parent
DEBUG_LOG = install_debug_log()
# English is the deterministic server-rendered fallback language: the actual
# translation for the request's chosen language happens client-side (see
# static/i18n.js), keyed by the same identifiers stored here.
_LOCALE_EN: dict[str, str] = json.loads((BASE_DIR / "static" / "i18n" / "en.json").read_text(encoding="utf-8"))
# Cache-busting token for static assets: changes on every process restart (i.e. every
# deploy) so browsers don't keep serving JS/CSS cached from before the restart.
ASSET_VERSION = str(int(datetime.now().timestamp()))

CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"
# The bearer-token API (/api/v1/...) and the MCP endpoint authenticate with
# a header the browser never attaches on its own, so cross-site requests
# can't forge them the way a cookie-authenticated form/fetch call can.
CSRF_EXEMPT_PREFIXES = ("/api/v1/", "/mcp")


async def _csrf_protect(request: Request, call_next):
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return await call_next(request)
    if request.url.path.startswith(CSRF_EXEMPT_PREFIXES):
        return await call_next(request)
    expected = request.session.get("csrf_token")
    if not expected:
        # Nothing forgeable belongs to this visitor yet - every GET mints a
        # token (see _csrf_context) before any real form is rendered, so
        # this only lets through requests that never loaded a page first.
        return await call_next(request)
    submitted = request.headers.get(CSRF_HEADER_NAME, "")
    if not submitted:
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            # Request.body() must run before Request.form() here: it caches
            # the raw bytes on this Request instance, which is what lets
            # BaseHTTPMiddleware's _CachedRequest replay the body to the
            # route handler's own Request afterwards. Calling .form()
            # directly instead drains the ASGI receive channel without
            # caching anything, so the route would see an empty body.
            await request.body()
            form = await request.form()
            submitted = str(form.get(CSRF_FORM_FIELD, ""))
    if not submitted or not hmac.compare_digest(submitted, expected):
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"error": "csrf_token_invalid"}, status_code=status.HTTP_403_FORBIDDEN)
        _set_flash(
            request,
            "common.raw_message",
            {"message": "Your session could not be verified. Please try again."},
            "error",
        )
        referer_path = urlsplit(request.headers.get("referer", "")).path
        return _redirect(_safe_internal_path(referer_path, "/"))
    return await call_next(request)


async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    # Home Assistant Ingress legitimately embeds the whole app in an iframe
    # inside the HA frontend (see app/tbc/ingress.py) - request.state.ingress_prefix
    # is only ever non-empty for requests that actually came through that
    # trusted Supervisor proxy, so clickjacking defenses are skipped there
    # and enforced everywhere else, where this app has no embed use case.
    if not (getattr(request.state, "ingress_prefix", "") or ""):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    if SETTINGS.cookie_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


app = FastAPI(title="TBC - TB Camera", docs_url="/api/docs", redoc_url="/api/redoc")
# Starlette's add_middleware() makes the most-recently-added middleware the
# outermost one (see build_middleware_stack()), i.e. dispatch order below is
# Ingress -> Session -> CSRF -> SecurityHeaders -> routes. CSRF and
# SecurityHeaders are added *before* Session here specifically so they end
# up dispatching *after* Session/Ingress have populated request.session and
# request.state (add_middleware() prepends, so earlier == more inner).
app.add_middleware(BaseHTTPMiddleware, dispatch=_security_headers)
app.add_middleware(BaseHTTPMiddleware, dispatch=_csrf_protect)
app.add_middleware(
    SessionMiddleware,
    secret_key=SETTINGS.secret_key,
    same_site="lax",
    https_only=SETTINGS.cookie_secure,
    max_age=SETTINGS.session_max_age_seconds,
)
# Registering this *after* SessionMiddleware is what makes it wrap it -
# required so it can rewrite the Set-Cookie header SessionMiddleware just
# emitted, and so it sets scope["root_path"]/state before SessionMiddleware
# or any route runs.
app.add_middleware(IngressPathMiddleware)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def _active_theme_context(request: Request) -> dict[str, Any]:
    theme_key = database.get_active_theme_key(SETTINGS.database_path)
    try:
        registration = get_theme_registration(theme_key)
    except UnknownThemeError:
        return {"active_theme": None}
    return {"active_theme": registration.manifest}


def _pending_plugin_updates_context(request: Request) -> dict[str, Any]:
    return {"pending_plugin_update_count": database.count_plugin_sources_with_update(SETTINGS.database_path)}


def _app_update_context(request: Request) -> dict[str, Any]:
    return {
        "app_version": __version__,
        "app_update_available": APP_UPDATE_STATE["update_available"],
        "app_latest_version": APP_UPDATE_STATE["latest_version"],
        "app_update_url": APP_UPDATE_STATE["html_url"],
    }


def _ingress_context(request: Request) -> dict[str, Any]:
    # Empty string outside Home Assistant Ingress - see app/tbc/ingress.py.
    return {"ingress_prefix": request.state.ingress_prefix}


def _ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
    return token


def _csrf_context(request: Request) -> dict[str, Any]:
    return {"csrf_token": _ensure_csrf_token(request)}


templates = Jinja2Templates(
    directory=BASE_DIR / "templates",
    context_processors=[
        _active_theme_context,
        _pending_plugin_updates_context,
        _app_update_context,
        _ingress_context,
        _csrf_context,
    ],
)
templates.env.filters["redact_rtsp_credentials"] = redact_rtsp_credentials
templates.env.filters["tojson"] = tojson_html_safe
templates.env.globals["asset_version"] = ASSET_VERSION
RECORDING_MANAGER = RecordingManager(SETTINGS.database_path)
CONTINUOUS_RECORDING_MANAGER = ContinuousRecordingManager(SETTINGS.database_path)
LIVE_MANAGER = LiveManager(SETTINGS.live_path)
GO2RTC_MANAGER = Go2rtcManager(str(Path(SETTINGS.live_path) / "go2rtc"))
SNAPSHOT_MANAGER = DashboardSnapshotManager(
    SETTINGS.dashboard_snapshots_path,
    interval_seconds=SETTINGS.dashboard_snapshot_interval_seconds,
)
SNAPSHOT_SEMAPHORE = asyncio.Semaphore(2)
CONTROL_STATE_CACHE: dict[int, dict[str, Any]] = {}
# Tracks (camera_id, channel) probes currently in flight and, after a failed
# attempt, the earliest time a new one may start. Without this, every page that
# lazily kicks off a probe when the cache is empty (the live grid re-checks on
# every ~3s poll, for every camera) would otherwise queue up a fresh concurrent
# probe each cycle for any camera that hasn't answered yet - most cameras only
# accept one ONVIF/vendor-API session at a time, so the flood itself prevents
# the probe from ever completing.
CONTROL_STATE_PROBES_IN_FLIGHT: set[tuple[int, int]] = set()
CONTROL_STATE_PROBE_RETRY_AFTER: dict[tuple[int, int], float] = {}
CONTROL_STATE_PROBE_RETRY_COOLDOWN_SECONDS = 30
# Upper bound for a single device round-trip. reolink-aio in particular can spend
# 25-30s retrying multiple login/encryption strategies against an unreachable or
# slow camera before it ever raises, which would otherwise hang a control button
# (or the background cache refresh) far longer than any UI should keep a user
# waiting on a single click.
CONTROL_TIMEOUT_SECONDS = 20
# One controller call (discover_devices) returns every client the account
# knows about, so this is cached per network_account_id rather than per
# camera - every camera mapped to that account is served from the same
# refresh, mirroring CONTROL_STATE_CACHE's lazy-probe/background-refresh
# pattern above so a camera-detail page view never blocks on a live
# network-controller round-trip.
NETWORK_STATE_CACHE: dict[int, list[dict[str, Any]]] = {}
NETWORK_STATE_PROBES_IN_FLIGHT: set[int] = set()
NETWORK_STATE_PROBE_RETRY_AFTER: dict[int, float] = {}
NETWORK_STATE_PROBE_RETRY_COOLDOWN_SECONDS = 30
PLUGIN_SOURCE_FETCH_TIMEOUT_SECONDS = 30
PLUGIN_SOURCE_UPDATE_CHECK_INTERVAL_SECONDS = 60 * 60
APP_UPDATE_CHECK_INTERVAL_SECONDS = 60 * 60
# Firmware updates run as a background task (they can take several minutes -
# far longer than any request should block on) and are polled by the browser
# via this in-memory state, keyed by (camera_id, channel). Not persisted: a
# TBC restart mid-update just loses the progress display, not the update
# itself, which keeps running on the camera independently of TBC.
FIRMWARE_UPDATE_STATE: dict[tuple[int, int], dict[str, Any]] = {}
# Whether a newer TBC release exists on GitHub. Re-checked hourly in the
# background (see _app_update_check_loop) and shown in the nav - unlike plugin
# updates, applying this requires pulling a new image/commit by hand, so it is
# only ever a notice, never a one-click install.
APP_UPDATE_STATE: dict[str, Any] = {
    "latest_version": None,
    "update_available": False,
    "html_url": "",
    "checked_at": None,
    "error": None,
}
# MCP server (AI interface, see docs/mcp.md) - shares the enable switch and
# API key with the /api/v1/... read API (app/tbc/api_common.py). The session
# manager needs its own running task-group context, which a plain app.mount()
# does not start - so it is opened/closed explicitly in the app's lifespan
# (see _lifespan further down), around the rest of startup/shutdown.
MCP_APP, MCP_SESSION_MANAGER_CM = build_mcp_app(
    database_path=SETTINGS.database_path,
    app_name=SETTINGS.app_name,
    app_version=__version__,
    app_update_state=APP_UPDATE_STATE,
    snapshot_manager=SNAPSHOT_MANAGER,
    snapshot_semaphore=SNAPSHOT_SEMAPHORE,
    stream_uri_for=stream_uri_for,
)
app.mount("/mcp", MCP_APP)


LOCAL_AI_TRIGGER_DEFINITIONS = tuple(
    DetectionDefinition(key=key, label=label, category="ai")
    for key, label in {**DETECTION_KEY_LABELS, **LOITERING_KEY_LABELS, **AUDIO_KEY_LABELS}.items()
)
DETECTION_MODEL_PATH = Path(SETTINGS.detection_models_path) / "default.onnx"
DETECTION_MODEL_METADATA_PATH = Path(SETTINGS.detection_models_path) / "default.json"
DETECTION_CORAL_MODEL_PATH = Path(SETTINGS.detection_models_path) / "default_edgetpu.tflite"
DETECTION_CORAL_MODEL_METADATA_PATH = Path(SETTINGS.detection_models_path) / "default_edgetpu.json"
RECOGNITION_MODELS_DIR = Path(SETTINGS.detection_models_path)
RECOGNITION_SNAPSHOT_DIR = Path(SETTINGS.recordings_path) / "recognition-events"
AUDIO_MODEL_PATH = Path(SETTINGS.detection_models_path) / "audio_default.onnx"
AUDIO_MODEL_METADATA_PATH = Path(SETTINGS.detection_models_path) / "audio_default.json"


def _detection_backend_factory(settings: dict[str, Any], module_key: str | None = None):
    plugin_model = resolve_plugin_model(module_key, cache_root=Path(SETTINGS.detection_models_path))
    if plugin_model:
        model_path, metadata_path = plugin_model
        return detection_factory.build_backend(settings, model_path=str(model_path), metadata_path=str(metadata_path))
    backend_key = str(settings.get("backend") or "cpu").strip().lower()
    if backend_key == "coral":
        # Downloaded lazily on first use, not eagerly at startup like the ONNX
        # default - most installs never select this backend.
        ensure_default_coral_model(DETECTION_CORAL_MODEL_PATH, DETECTION_CORAL_MODEL_METADATA_PATH)
        return detection_factory.build_backend(
            settings,
            model_path=str(DETECTION_CORAL_MODEL_PATH),
            metadata_path=str(DETECTION_CORAL_MODEL_METADATA_PATH),
        )
    return detection_factory.build_backend(
        settings,
        model_path=str(DETECTION_MODEL_PATH),
        metadata_path=str(DETECTION_MODEL_METADATA_PATH),
    )


def _audio_detection_backend_factory(settings: dict[str, Any]):
    return audio_detection_factory.build_backend(
        settings,
        model_path=str(AUDIO_MODEL_PATH),
        metadata_path=str(AUDIO_MODEL_METADATA_PATH),
    )


def _process_frame_detections(camera_id: int, frame: Any, detections: list[Detection]) -> None:
    """Fired once per processed frame that has at least one filtered detection (see
    detection.supervisor._run_worker_once). Fans out qualifying person/vehicle detections to
    face/plate recognition in "live" mode - fire-and-forget via asyncio.create_task so a slow
    first-time model download or a slow inference pass never stalls that camera's detection loop.
    """
    relevant = [
        detection
        for detection in detections
        if detection.detection_key in FACE_TRIGGER_DETECTION_KEYS
        or detection.detection_key in PLATE_TRIGGER_DETECTION_KEYS
    ]
    if not relevant:
        return
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if camera is None:
        return
    frame_copy = frame.copy()
    for detection in relevant:
        asyncio.create_task(
            asyncio.to_thread(
                process_recognition,
                SETTINGS.database_path,
                RECOGNITION_MODELS_DIR,
                camera_id=camera_id,
                camera_name=str(camera["name"]),
                recording_id=None,
                detection_key=detection.detection_key,
                mode="live",
                image=frame_copy,
                box=detection.box,
                public_base_url=SETTINGS.public_base_url,
                snapshot_dir=RECOGNITION_SNAPSHOT_DIR,
            )
        )


async def _detection_supervisor_loop() -> None:
    await detection_supervisor(
        SETTINGS.database_path,
        on_detections=_process_detection_states,
        backend_factory=_detection_backend_factory,
        on_frame_detections=_process_frame_detections,
    )


async def _audio_detection_supervisor_loop() -> None:
    await audio_detection_supervisor(
        SETTINGS.database_path,
        on_detections=_process_detection_states,
        backend_factory=_audio_detection_backend_factory,
    )


def _start_go2rtc() -> None:
    try:
        GO2RTC_MANAGER.start()
    except RuntimeError as exc:
        LOGGER.warning("WebRTC live view is enabled but could not start go2rtc: %s", exc)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Manual enter/exit (rather than nesting the whole lifespan inside
    # `async with MCP_SESSION_MANAGER_CM:`) to preserve the exact
    # startup/shutdown ordering the two separate on_event handlers used to
    # give: MCP session manager starts first and stops first, go2rtc stops
    # last.
    await MCP_SESSION_MANAGER_CM.__aenter__()

    database.initialize(SETTINGS.database_path, SETTINGS.recordings_path)
    database.ensure_admin_user(
        SETTINGS.database_path,
        SETTINGS.admin_username,
        SETTINGS.admin_password,
    )
    asyncio.create_task(_poll_loop())
    asyncio.create_task(_camera_event_supervisor())
    asyncio.create_task(_health_loop())
    asyncio.create_task(_cleanup_loop())
    asyncio.create_task(_snapshot_loop())
    asyncio.create_task(_continuous_recording_loop())
    asyncio.create_task(_plugin_source_update_check_loop())
    asyncio.create_task(_app_update_check_loop())
    asyncio.create_task(mqtt.run_control_listener(SETTINGS.database_path))
    asyncio.create_task(asyncio.to_thread(ensure_default_model, DETECTION_MODEL_PATH, DETECTION_MODEL_METADATA_PATH))
    asyncio.create_task(
        asyncio.to_thread(
            ensure_audio_model, AUDIO_MODEL_PATH, AUDIO_MODEL_METADATA_PATH, model_url=SETTINGS.audio_model_url
        )
    )
    # Face/plate recognition models are opt-in and otherwise download lazily on first use
    # (see detection.recognition.get_face_recognizer/get_plate_recognizer) - if a previous
    # session already enabled a feature, pre-warm it here so the first real detection after
    # a restart doesn't stall on a multi-MB download.
    recognition_settings = database.get_recognition_settings(SETTINGS.database_path)
    if recognition_settings.get("face_enabled"):
        asyncio.create_task(
            asyncio.to_thread(
                ensure_face_models,
                RECOGNITION_MODELS_DIR / "face_detection_yunet.onnx",
                RECOGNITION_MODELS_DIR / "face_recognition_sface.onnx",
            )
        )
    if recognition_settings.get("plate_enabled"):
        asyncio.create_task(
            asyncio.to_thread(
                ensure_plate_models,
                RECOGNITION_MODELS_DIR / "plate_detector.onnx",
                RECOGNITION_MODELS_DIR / "plate_ocr.onnx",
                RECOGNITION_MODELS_DIR / "plate_ocr_config.yaml",
            )
        )
    asyncio.create_task(_detection_supervisor_loop())
    asyncio.create_task(_audio_detection_supervisor_loop())
    if database.get_live_wall_settings(SETTINGS.database_path).get("webrtc_enabled"):
        asyncio.create_task(asyncio.to_thread(_start_go2rtc))

    yield

    await MCP_SESSION_MANAGER_CM.__aexit__(None, None, None)
    await asyncio.to_thread(GO2RTC_MANAGER.stop)


app.router.lifespan_context = _lifespan


# In-process brute-force throttle, keyed by username rather than client IP:
# uvicorn runs as a single worker/process here (see container_launcher.py),
# so a plain module-level dict is safe, and keying by username protects a
# given account regardless of how many source IPs (or a proxy in front of
# TBC) an attacker spreads guesses across. {username: (fail_count, locked_until_monotonic)}.
_LOGIN_ATTEMPTS: dict[str, tuple[int, float]] = {}
_LOGIN_LOCKOUT_THRESHOLD = 5
_LOGIN_LOCKOUT_BASE_SECONDS = 30
_LOGIN_LOCKOUT_MAX_SECONDS = 15 * 60
_LOGIN_ATTEMPTS_PRUNE_AT = 10_000


def _login_attempts_key(username: str) -> str:
    return username.strip().lower()[:256]


def _login_lockout_remaining_seconds(username: str) -> float:
    _, locked_until = _LOGIN_ATTEMPTS.get(_login_attempts_key(username), (0, 0.0))
    remaining = locked_until - _monotonic()
    return remaining if remaining > 0 else 0.0


def _register_login_failure(username: str) -> None:
    key = _login_attempts_key(username)
    fail_count = _LOGIN_ATTEMPTS.get(key, (0, 0.0))[0] + 1
    locked_until = 0.0
    if fail_count >= _LOGIN_LOCKOUT_THRESHOLD:
        delay = min(
            _LOGIN_LOCKOUT_BASE_SECONDS * (2 ** (fail_count - _LOGIN_LOCKOUT_THRESHOLD)),
            _LOGIN_LOCKOUT_MAX_SECONDS,
        )
        locked_until = _monotonic() + delay
    _LOGIN_ATTEMPTS[key] = (fail_count, locked_until)
    if len(_LOGIN_ATTEMPTS) > _LOGIN_ATTEMPTS_PRUNE_AT:
        _prune_login_attempts()


def _register_login_success(username: str) -> None:
    _LOGIN_ATTEMPTS.pop(_login_attempts_key(username), None)


def _prune_login_attempts() -> None:
    now = _monotonic()
    expired = [key for key, (_, locked_until) in _LOGIN_ATTEMPTS.items() if locked_until < now]
    for key in expired:
        del _LOGIN_ATTEMPTS[key]


def _firmware_camera_and_module(camera_id: int) -> tuple[dict[str, Any] | None, Any, Any]:
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return None, None, JSONResponse({"ok": False, "message": "Camera was not found"}, status_code=status.HTTP_404_NOT_FOUND)
    try:
        camera_module = get_camera_module(camera.get("module_key"))
    except UnknownCameraModuleError as exc:
        return None, None, JSONResponse({"ok": False, "message": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)
    if not camera_module.supports(CameraCapability.FIRMWARE):
        return None, None, JSONResponse(
            {"ok": False, "message": f"The {camera_module.label} module does not support firmware updates"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return camera, camera_module, None


async def _run_firmware_update_task(camera_id: int, camera: dict[str, Any], camera_module: Any, channel: int) -> None:
    key = (camera_id, channel)

    def on_progress(progress: int) -> None:
        entry = FIRMWARE_UPDATE_STATE.get(key, {})
        FIRMWARE_UPDATE_STATE[key] = {**entry, "status": "updating", "progress": progress}

    try:
        await camera_module.update_firmware(camera, channel=channel, progress_callback=on_progress)
    except Exception as exc:
        LOGGER.exception("Firmware-Update fuer Kamera %s Kanal %s fehlgeschlagen", camera_id, channel)
        entry = FIRMWARE_UPDATE_STATE.get(key, {})
        FIRMWARE_UPDATE_STATE[key] = {**entry, "status": "failed", "progress": 0, "message": str(exc)}
        return
    entry = FIRMWARE_UPDATE_STATE.get(key, {})
    FIRMWARE_UPDATE_STATE[key] = {
        **entry,
        "status": "done",
        "progress": 100,
        "message": "Firmware was updated",
        "update_available": False,
    }
    for cache_key in [k for k in CONTROL_STATE_CACHE if k[0] == camera_id]:
        CONTROL_STATE_CACHE.pop(cache_key, None)
    _kick_off_control_probe(camera_id, camera, camera_module, channel=channel)


async def _execute_control(request: Request, camera_id: int, *, action: str, params: dict[str, Any], channel: int = 0):
    # The control forms in the "Steuerung" tab are progressively enhanced: JS
    # submits them via fetch with this header and renders the JSON result as a
    # toast without a full page reload; without JS (or for the header-less
    # case) the exact same route falls back to the classic flash+redirect flow.
    is_ajax = request.headers.get("X-Requested-With") == "fetch"

    def fail(message: str, *, status_code: int, redirect_to: str | None = None) -> Any:
        if is_ajax:
            return JSONResponse({"ok": False, "message": message}, status_code=status_code)
        _set_flash(request, "common.raw_message", {"message": message}, "error")
        return _redirect(redirect_to or f"/cameras/{camera_id}?control_channel={channel}#control")

    guard = _require_admin(request)
    if guard:
        return fail("Administrator permissions are required", status_code=status.HTTP_403_FORBIDDEN) if is_ajax else guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return fail("Camera was not found", status_code=status.HTTP_404_NOT_FOUND, redirect_to="/cameras")
    try:
        camera_module = get_camera_module(camera.get("module_key"))
    except UnknownCameraModuleError as exc:
        return fail(str(exc), status_code=status.HTTP_404_NOT_FOUND)
    if not camera_module.supports(CameraCapability.CONTROL):
        return fail(f"The {camera_module.label} module does not support camera control", status_code=status.HTTP_400_BAD_REQUEST)
    try:
        await asyncio.wait_for(
            camera_module.send_control(camera, action=action, channel=channel, **params),
            timeout=CONTROL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        LOGGER.info("Control action %s timed out for camera %s channel %s", action, camera_id, channel)
        return fail(
            f"Command aborted: camera did not respond within {CONTROL_TIMEOUT_SECONDS}s",
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except Exception as exc:
        LOGGER.info("Control action %s failed for camera %s channel %s: %s", action, camera_id, channel, exc)
        return fail(f"Befehl fehlgeschlagen: {exc}", status_code=status.HTTP_502_BAD_GATEWAY)
    _kick_off_control_probe(camera_id, camera, camera_module, channel=channel)
    if is_ajax:
        return {"ok": True, "message": "Command was sent"}
    _set_flash(request, "camera.command_sent")
    return _redirect(f"/cameras/{camera_id}?control_channel={channel}#control")


def _kick_off_control_probe(camera_id: int, camera: dict[str, Any], camera_module: Any, *, channel: int = 0) -> None:
    key = (camera_id, channel)
    if key in CONTROL_STATE_PROBES_IN_FLIGHT:
        return
    retry_after = CONTROL_STATE_PROBE_RETRY_AFTER.get(key)
    if retry_after is not None and asyncio.get_running_loop().time() < retry_after:
        return
    CONTROL_STATE_PROBES_IN_FLIGHT.add(key)
    asyncio.create_task(_publish_control_state(camera_id, camera, camera_module, channel=channel))


async def _publish_control_state(camera_id: int, camera: dict[str, Any], camera_module: Any, *, channel: int = 0) -> None:
    key = (camera_id, channel)
    try:
        try:
            control_state = await asyncio.wait_for(
                camera_module.get_control_state(camera, channel=channel),
                timeout=CONTROL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            LOGGER.debug("Control state fetch timed out for camera %s channel %s", camera_id, channel)
            CONTROL_STATE_PROBE_RETRY_AFTER[key] = (
                asyncio.get_running_loop().time() + CONTROL_STATE_PROBE_RETRY_COOLDOWN_SECONDS
            )
            return
        except Exception:
            LOGGER.debug("Control state fetch failed for camera %s channel %s", camera_id, channel, exc_info=True)
            CONTROL_STATE_PROBE_RETRY_AFTER[key] = (
                asyncio.get_running_loop().time() + CONTROL_STATE_PROBE_RETRY_COOLDOWN_SECONDS
            )
            return
        CONTROL_STATE_CACHE[key] = control_state
        CONTROL_STATE_PROBE_RETRY_AFTER.pop(key, None)
        await asyncio.to_thread(mqtt.publish_control_state, SETTINGS.database_path, camera, control_state)
    finally:
        CONTROL_STATE_PROBES_IN_FLIGHT.discard(key)


def _kick_off_network_probe(network_account_id: int) -> None:
    if network_account_id in NETWORK_STATE_PROBES_IN_FLIGHT:
        return
    retry_after = NETWORK_STATE_PROBE_RETRY_AFTER.get(network_account_id)
    if retry_after is not None and asyncio.get_running_loop().time() < retry_after:
        return
    NETWORK_STATE_PROBES_IN_FLIGHT.add(network_account_id)
    asyncio.create_task(_publish_network_state(network_account_id))


async def _publish_network_state(network_account_id: int) -> None:
    try:
        account = database.get_network_account(SETTINGS.database_path, network_account_id)
        if not account:
            return
        try:
            network_module = get_network_module(account["module_key"])
        except UnknownNetworkModuleError:
            return
        try:
            devices = await asyncio.wait_for(
                network_module.discover_devices(account), timeout=CONTROL_TIMEOUT_SECONDS
            )
        except (asyncio.TimeoutError, NetworkConnectionError):
            LOGGER.debug("Network device fetch failed for account %s", network_account_id, exc_info=True)
            NETWORK_STATE_PROBE_RETRY_AFTER[network_account_id] = (
                asyncio.get_running_loop().time() + NETWORK_STATE_PROBE_RETRY_COOLDOWN_SECONDS
            )
            return
        except Exception:
            LOGGER.debug("Network device fetch failed for account %s", network_account_id, exc_info=True)
            NETWORK_STATE_PROBE_RETRY_AFTER[network_account_id] = (
                asyncio.get_running_loop().time() + NETWORK_STATE_PROBE_RETRY_COOLDOWN_SECONDS
            )
            return
        NETWORK_STATE_CACHE[network_account_id] = [_network_device_to_dict(device) for device in devices]
        NETWORK_STATE_PROBE_RETRY_AFTER.pop(network_account_id, None)
        _record_network_device_status(network_account_id, NETWORK_STATE_CACHE[network_account_id])
    finally:
        NETWORK_STATE_PROBES_IN_FLIGHT.discard(network_account_id)


def _record_network_device_status(network_account_id: int, devices: list[dict[str, Any]]) -> None:
    """Persist each mapped camera's connectivity so offline devices still show

    where they were last connected (network_mappings.html's tree) and build
    up a per-camera history (network_device_events). A camera missing from
    `devices` (the controller no longer reports it - offline, or briefly
    dropped from the client list) falls back to whatever location/signal was
    last known instead of erasing it.
    """
    devices_by_mac = {str(device["mac_address"]).strip().lower(): device for device in devices}
    for camera in database.list_cameras(SETTINGS.database_path):
        if camera.get("network_account_id") != network_account_id:
            continue
        mac = camera.get("network_device_mac")
        if not mac:
            continue
        camera_id = int(camera["id"])
        device = devices_by_mac.get(mac)
        online = device.get("online") if device else False
        connection_type = device.get("connection_type") if device else None
        uplink_name = device.get("uplink_name") if device else None
        signal_dbm = device.get("signal_dbm") if device else None
        if not uplink_name:
            previous = database.get_network_device_status(SETTINGS.database_path, camera_id)
            if previous:
                connection_type = connection_type or previous["connection_type"]
                uplink_name = uplink_name or previous["uplink_name"]
                signal_dbm = signal_dbm if signal_dbm is not None else previous["signal_dbm"]
        database.upsert_network_device_status(
            SETTINGS.database_path,
            camera_id,
            online=online,
            connection_type=connection_type,
            uplink_name=uplink_name,
            signal_dbm=signal_dbm,
        )


def _network_device_to_dict(device: Any) -> dict[str, Any]:
    return {
        "mac_address": device.mac_address,
        "name": device.name,
        "ip_address": device.ip_address,
        "online": device.online,
        "connection_type": device.connection_type,
        "uplink_name": device.uplink_name,
        "signal_dbm": device.signal_dbm,
        "last_seen": device.last_seen,
    }


RECORDINGS_PAGE_SIZE = 60


async def _refresh_camera(camera_id: int):
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if camera is None:
        raise ValueError(f"camera {camera_id} does not exist")
    camera_module = get_camera_module(camera.get("module_key"))
    snapshot = await camera_module.probe(camera)
    database.update_camera_probe(
        SETTINGS.database_path,
        camera_id,
        status=snapshot.status,
        message=snapshot.message,
        manufacturer=snapshot.manufacturer,
        model=snapshot.model,
        firmware=snapshot.firmware,
        serial=snapshot.serial,
        stream_uri=snapshot.stream_uri,
        metrics=snapshot.metrics,
    )
    if camera_module.supports(CameraCapability.CHANNELS) and snapshot.channels:
        database.upsert_camera_channels(SETTINGS.database_path, camera_id, snapshot.channels)
    _process_detection_states(camera_id, snapshot.detections, camera_module)
    if camera_module.supports(CameraCapability.CONTROL):
        _kick_off_control_probe(camera_id, camera, camera_module)
    return snapshot


def _process_detection_states(camera_id: int, detections: list[dict[str, Any]], camera_module=None) -> None:
    channels = database.list_camera_channels(SETTINGS.database_path, camera_id)
    detections = apply_channel_enabled_filter(detections, channels)
    database.replace_detections(SETTINGS.database_path, camera_id, detections)
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if camera is None:
        return
    asyncio.create_task(asyncio.to_thread(mqtt.publish_detection_states, SETTINGS.database_path, camera, detections))
    # Local AI detections (video or audio) are TBC's own inference over the raw stream,
    # not a vendor capability - recording for them uses plain ffmpeg against
    # camera["stream_uri"] and works regardless of what the assigned camera module declares.
    is_local_ai_source = any(
        detection.get("source") in {"local_ai", "local_ai_audio"} for detection in detections
    )
    camera_module = camera_module or get_camera_module(camera.get("module_key"))
    if is_local_ai_source or camera_module.supports(CameraCapability.RECORDING):
        RECORDING_MANAGER.maybe_start_event_recordings(camera, detections)


def _password_field_keys(fields: Iterable[Any]) -> tuple[str, ...]:
    """Return the config_json keys of a module's password-type account fields.

    Tells database.py's account create/update functions which custom-named
    fields (e.g. an "email"/"password" pair instead of the generic
    "identifier"/"secret") need encrypting - without this, only a field
    literally named "secret" ever got encrypted.
    """
    return tuple(field.key for field in fields if field.field_type.value == "password")


def _network_module_selector_options() -> list[dict[str, Any]]:
    registrations = list_network_module_registrations()
    options = [
        {
            "key": registration.module.key,
            "label": registration.module.label,
            "description": registration.module.description,
            "installed": True,
            "install_url": "/plugin-sources",
        }
        for registration in registrations
    ]
    candidates = list_uninstalled_plugin_candidates(
        "network",
        (registration.module.key for registration in registrations),
        database.list_plugin_sources(SETTINGS.database_path),
    )
    options.extend(
        {
            "key": candidate.key,
            "label": candidate.label,
            "description": candidate.description,
            "installed": False,
            "install_url": candidate.install_url,
        }
        for candidate in candidates
    )
    return options


def _network_topology(mapped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group mapped cameras by network account, then by the switch/AP they
    connect through - a real (if two-level-deep) tree under each account's
    controller, not just a flat list of switches/APs.

    `network_device_status` (kept in sync on every probe, see
    _record_network_device_status) is preferred over the live probe cache so
    an offline camera - or one the controller briefly reports nothing for -
    still shows up under the switch/AP it was last connected to, instead of
    disappearing from the tree the moment it drops offline. The provider
    only tells us a camera's own immediate uplink, not that switch/AP's own
    uplink, so this cannot go deeper than account -> uplink device -> camera.
    """
    accounts: dict[Any, dict[str, Any]] = {}
    for entry in mapped:
        source = entry.get("last_status") or entry.get("state")
        uplink_name = (source or {}).get("uplink_name")
        if not uplink_name:
            continue
        account = entry.get("account")
        account_id = account["id"] if account else 0
        account_bucket = accounts.setdefault(
            account_id, {"account_label": account["label"] if account else "–", "groups": {}}
        )
        events = entry.get("events") or []
        account_bucket["groups"].setdefault(uplink_name, []).append(
            {
                **entry,
                "online": (source or {}).get("online"),
                "uplink_name": uplink_name,
                "last_seen": events[0]["created_at"] if events else None,
            }
        )
    result = []
    for bucket in sorted(accounts.values(), key=lambda item: item["account_label"].lower()):
        groups = [
            {"uplink_name": name, "cameras": cameras}
            for name, cameras in sorted(bucket["groups"].items(), key=lambda item: item[0].lower())
        ]
        result.append(
            {
                "account_label": bucket["account_label"],
                "groups": groups,
                "total_cameras": sum(len(group["cameras"]) for group in groups),
            }
        )
    return result


_PLUGIN_TEMPLATE_BUILDERS = {
    "camera": (build_camera_plugin_template, "acme_camera"),
    "cloud": (build_cloud_plugin_template, "acme_cloud"),
    "network": (build_network_plugin_template, "acme_network"),
    "design": (build_design_theme_template, "acme_design"),
}


def _find_registered_standard_source(
    standard_source: StandardPluginSource, sources: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for source in sources:
        if source["plugin_kind"] != standard_source.plugin_kind:
            continue
        try:
            matches = github_repositories_match(standard_source.repo_url, source["repo_url"])
        except PluginSourceError:
            continue
        if matches:
            return source
    return None


async def _sync_plugin_source(request: Request, source_id: int, redirect_target: str):
    source = database.get_plugin_source(SETTINGS.database_path, source_id)
    if not source:
        _set_flash(request, "plugin_source.not_found", None, "error")
        return _redirect(redirect_target)
    try:
        archive, resolved_sha = await asyncio.wait_for(
            asyncio.to_thread(
                resolve_and_fetch_plugin, source["repo_url"], source["ref"], source["subdirectory"]
            ),
            timeout=PLUGIN_SOURCE_FETCH_TIMEOUT_SECONDS,
        )
        installed_key = _install_plugin_for_kind(source["plugin_kind"], archive)
    except asyncio.TimeoutError:
        message = f"GitHub antwortet nicht innerhalb von {PLUGIN_SOURCE_FETCH_TIMEOUT_SECONDS}s"
        database.update_plugin_source_sync_result(SETTINGS.database_path, source_id, status="error", message=message)
        _set_flash(request, "common.raw_message", {"message": message}, "error")
        return _redirect(redirect_target)
    except MissingPluginRequirements as exc:
        database.update_plugin_source_sync_result(
            SETTINGS.database_path,
            source_id,
            status="error",
            message=f"Missing Python packages: {', '.join(exc.missing)}",
        )
        return _redirect_to_requirements_confirm(exc, redirect_target, source_id=source_id)
    except (PluginSourceError, ValueError, OSError) as exc:
        database.update_plugin_source_sync_result(SETTINGS.database_path, source_id, status="error", message=str(exc))
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(redirect_target)
    database.update_plugin_source_sync_result(
        SETTINGS.database_path,
        source_id,
        status="ok",
        message=f"Installiert als '{installed_key}'",
        installed_key=installed_key,
        installed_ref_sha=resolved_sha,
    )
    _set_flash(request, "plugin.installed_or_updated", {"key": installed_key})
    return _redirect(redirect_target)


def _documentation_response(request: Request, document_name: str):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    document_path = _resolve_documentation_file(document_name)
    document_source = document_path.read_text(encoding="utf-8") if document_path else ""
    return templates.TemplateResponse(
        request,
        "docs.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "documents": _documentation_files(),
            "current_document": document_path.name if document_path else None,
            "document_html": _render_documentation_markdown(document_source) if document_path else None,
            "flash": _pop_flash(request),
        },
        status_code=status.HTTP_200_OK if document_path else status.HTTP_404_NOT_FOUND,
    )


# --- Public, API-key-secured read API for external integrations (/api/v1/...) ---
# Separate from the internal /api/... routes above, which use session-cookie auth
# for the app's own web UI. See docs/api.md. The serialization/auth helpers live in
# api_common.py so mcp_server.py can also use them without a circular import on main.py.


def _example_camera() -> dict[str, Any]:
    return {
        "id": 1,
        "name": "Einfahrt",
        "module_key": "reolink",
        "module_label": "Reolink",
        "capabilities": ["archive", "channels", "control", "detections", "firmware", "live", "recording"],
        "enabled": True,
        "manufacturer": "Reolink",
        "model": "RLC-823A",
        "firmware": "v3.1.0.4171",
        "status": "ok",
        "status_message": "ONVIF connection successful",
        "stream_uri": "rtsp://192.168.1.50:554/h264Preview_01_main",
        "recording_enabled": True,
        "continuous_recording_enabled": False,
        "snapshot_enabled": True,
        "detection_count": 12,
        "supported_count": 5,
        "active_count": 1,
        "snapshot_url": "/api/v1/cameras/1/snapshot",
        "created_at": "2026-05-02 08:11:04",
        "updated_at": "2026-07-14 09:32:51",
    }


def _example_recording() -> dict[str, Any]:
    return {
        "id": 512,
        "camera_id": 1,
        "camera_name": "Einfahrt",
        "detection_key": "ai_person",
        "label": "Person",
        "status": "ready",
        "started_at": "2026-07-14T08:15:03",
        "ended_at": "2026-07-14T08:15:48",
        "duration_seconds": 45,
        "size_bytes": 4213880,
        "mime_type": "video/mp4",
        "media_url": "/api/v1/recordings/512/media",
        "snapshot_url": "/api/v1/recordings/512/snapshot",
    }


def _example_storage_target() -> dict[str, Any]:
    return {
        "id": 1,
        "name": "Lokaler Speicher",
        "kind": "local",
        "local_path": "/recordings",
        "s3_bucket": None,
        "s3_region": None,
        "retention_days": 30,
        "retention_max_gb": 500,
    }


def _api_examples() -> list[dict[str, Any]]:
    camera = _example_camera()
    recording = _example_recording()
    storage_target = _example_storage_target()
    curl_prefix = 'curl -H "Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"'

    def _json(value: Any) -> str:
        return json.dumps(value, indent=2, ensure_ascii=False)

    return [
        {
            "method": "GET",
            "path": "/api/v1/status",
            "description_key": "api.description.status",
            "description": "Application name, version, update availability, and camera count.",
            "curl": f"{curl_prefix} https://tbc.example.com/api/v1/status",
            "response": _json(
                {
                    "app_name": "TBC",
                    "app_version": __version__,
                    "update_available": False,
                    "latest_version": None,
                    "camera_count": 3,
                }
            ),
        },
        {
            "method": "GET",
            "path": "/api/v1/cameras",
            "description_key": "api.description.cameras",
            "description": "All cameras with capabilities, status, and detection counts.",
            "curl": f"{curl_prefix} https://tbc.example.com/api/v1/cameras",
            "response": _json({"cameras": [camera]}),
        },
        {
            "method": "GET",
            "path": "/api/v1/cameras/{id}",
            "description_key": "api.description.camera",
            "description": "A single camera by ID.",
            "curl": f"{curl_prefix} https://tbc.example.com/api/v1/cameras/1",
            "response": _json(camera),
        },
        {
            "method": "GET",
            "path": "/api/v1/cameras/{id}/snapshot",
            "description_key": "api.description.camera_snapshot",
            "description": "The camera's current preview image as binary data, not JSON.",
            "curl": f"{curl_prefix} -o snapshot.jpg https://tbc.example.com/api/v1/cameras/1/snapshot",
            "response": None,
            "response_note_key": "api.response.jpeg",
            "response_note": "Response: image data with Content-Type: image/jpeg",
        },
        {
            "method": "GET",
            "path": "/api/v1/cameras/{id}/detections",
            "description_key": "api.description.camera_detections",
            "description": "The camera's current detection state for every configured detection type.",
            "curl": f"{curl_prefix} https://tbc.example.com/api/v1/cameras/1/detections",
            "response": _json(
                {
                    "camera_id": 1,
                    "detections": [
                        {
                            "id": 7,
                            "camera_id": 1,
                            "detection_key": "ai_person",
                            "label": "Person",
                            "category": "ai",
                            "channel": None,
                            "supported": 1,
                            "active": 1,
                            "source": "local_ai",
                            "last_seen": "2026-07-14 08:15:03",
                            "raw_value": '{"confidence": 0.94, "box": [0.31, 0.12, 0.58, 0.87]}',
                            "updated_at": "2026-07-14 08:15:03",
                        }
                    ],
                }
            ),
        },
        {
            "method": "GET",
            "path": "/api/v1/recordings",
            "description_key": "api.description.recordings",
            "description": "Recording list. Query parameters: camera_id, detection_key, date_from, date_to, limit (default 200, maximum 1000).",
            "curl": f"{curl_prefix} \"https://tbc.example.com/api/v1/recordings?camera_id=1&limit=20\"",
            "response": _json({"recordings": [recording]}),
        },
        {
            "method": "GET",
            "path": "/api/v1/recordings/{id}",
            "description_key": "api.description.recording",
            "description": "Metadata for a single recording.",
            "curl": f"{curl_prefix} https://tbc.example.com/api/v1/recordings/512",
            "response": _json(recording),
        },
        {
            "method": "GET",
            "path": "/api/v1/recordings/{id}/media",
            "description_key": "api.description.recording_media",
            "description": "Video clip as binary MP4 data with HTTP Range support for seeking.",
            "curl": f"{curl_prefix} -o clip.mp4 https://tbc.example.com/api/v1/recordings/512/media",
            "response": None,
            "response_note_key": "api.response.mp4",
            "response_note": "Response: video data with Content-Type: video/mp4",
        },
        {
            "method": "GET",
            "path": "/api/v1/recordings/{id}/snapshot",
            "description_key": "api.description.recording_snapshot",
            "description": "The recording's event preview image as binary data, not JSON.",
            "curl": f"{curl_prefix} -o event.jpg https://tbc.example.com/api/v1/recordings/512/snapshot",
            "response": None,
            "response_note_key": "api.response.jpeg",
            "response_note": "Response: image data with Content-Type: image/jpeg",
        },
        {
            "method": "GET",
            "path": "/api/v1/activity",
            "description_key": "api.description.activity",
            "description": "Event recordings across all cameras for one day. Query parameter: day (YYYY-MM-DD, defaults to today).",
            "curl": f"{curl_prefix} \"https://tbc.example.com/api/v1/activity?day=2026-07-14\"",
            "response": _json(
                {
                    "day": "2026-07-14",
                    "cameras": [
                        {"id": 1, "name": "Einfahrt", "events": [recording]},
                        {"id": 2, "name": "Garten", "events": []},
                    ],
                }
            ),
        },
        {
            "method": "GET",
            "path": "/api/v1/storage",
            "description_key": "api.description.storage",
            "description": "Configured storage destinations without credentials.",
            "curl": f"{curl_prefix} https://tbc.example.com/api/v1/storage",
            "response": _json({"storage_targets": [storage_target]}),
        },
        {
            "method": "GET",
            "path": "/api/v1/health",
            "description_key": "api.description.health",
            "description": "System usage and health status/events for cameras, storage, and MQTT.",
            "curl": f"{curl_prefix} https://tbc.example.com/api/v1/health",
            "response": _json(
                {
                    "system_usage": {
                        "checked_at": "2026-07-14 09:32:51",
                        "cpu_percent": 12.4,
                        "cpu_label": "12.4%",
                        "cpu_cores": 8,
                        "load_label": "Load 0.42, 0.38, 0.31",
                        "memory_percent": 47.1,
                        "memory_label": "47.1%",
                        "memory_used_mb": 3782.5,
                        "memory_total_mb": 8038.0,
                        "memory_detail": "3.7 GB von 7.9 GB belegt",
                    },
                    "items": [
                        {
                            "id": 1,
                            "component_type": "camera",
                            "component_id": "1",
                            "status": "ok",
                            "message": "Einfahrt: erreichbar",
                            "checked_at": "2026-07-14 09:32:51",
                        }
                    ],
                    "events": [
                        {
                            "id": 1,
                            "component_type": "camera",
                            "component_id": "1",
                            "previous_status": "error",
                            "status": "ok",
                            "message": "Einfahrt: erreichbar",
                            "created_at": "2026-07-14 09:32:51",
                        }
                    ],
                }
            ),
        },
    ]


def _mcp_tool_examples() -> list[dict[str, str]]:
    return [
        {"name": "list_cameras", "description_key": "mcp.description.cameras", "description": "All cameras with capabilities and status."},
        {"name": "get_camera", "description_key": "api.description.camera", "description": "A single camera by ID."},
        {"name": "get_camera_detections", "description_key": "mcp.description.camera_detections", "description": "The current detection state of a camera."},
        {"name": "get_camera_snapshot", "description_key": "mcp.description.camera_snapshot", "description": "A camera's current live preview as an image, not only a URL."},
        {"name": "list_recordings", "description_key": "mcp.description.recordings", "description": "Recordings filtered by camera, detection type, and date range."},
        {"name": "get_recording", "description_key": "api.description.recording", "description": "Metadata for a single recording."},
        {"name": "get_recording_snapshot", "description_key": "mcp.description.recording_snapshot", "description": "A recording's event preview image when a local snapshot exists."},
        {"name": "get_activity", "description_key": "mcp.description.activity", "description": "Event recordings across all cameras for one day."},
        {"name": "get_storage", "description_key": "api.description.storage", "description": "Configured storage destinations without credentials."},
        {"name": "get_health", "description_key": "mcp.description.health", "description": "System usage and health status/events."},
        {"name": "get_status", "description_key": "api.description.status", "description": "Application name, version, update availability, and camera count."},
    ]


def _api_stream_key(camera_id: int) -> str:
    # Kept separate from the browser-session live-view keys ("camera-{id}")
    # so an API/HA-driven stream and a logged-in user's live view of the same
    # camera don't share (and don't stop) each other's ffmpeg process.
    return f"api-camera-{camera_id}"


def _effective_api_key_value(request: Request) -> str | None:
    # Same bearer > X-API-Key > ?api_key= precedence api_auth_error applies,
    # but returns the raw credential string itself rather than a pass/fail -
    # needed to re-embed it into the playlist's segment URLs below.
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    value = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    return value.strip() if value else None


def _require_api_key_stream(request: Request) -> JSONResponse | None:
    # Same checks as _require_api_key, but also accepts ?api_key=... - the
    # HLS segments below are fetched directly by ffmpeg/PyAV inside Home
    # Assistant's stream integration, which cannot attach a custom header to
    # every request, so the URL has to be self-authenticating here.
    config = database.get_api_config(SETTINGS.database_path)
    api_key_value = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    error = api_auth_error(
        config,
        request.headers.get("Authorization"),
        api_key_value,
        find_token=lambda prefix: database.find_active_api_token_by_prefix(SETTINGS.database_path, prefix),
        on_success=lambda token: _stash_api_token(request, token),
    )
    if error:
        code, message = error
        return JSONResponse({"error": message}, status_code=code)
    request.state.api_key_value = _effective_api_key_value(request)
    return None


async def _resolve_api_stream_uri(camera_id: int) -> tuple[dict[str, Any] | None, str | None]:
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera or not _camera_supports(camera, CameraCapability.LIVE):
        return camera, None
    uri = stream_uri_for(camera)
    if not uri:
        await _refresh_camera(camera_id)
        camera = database.get_camera(SETTINGS.database_path, camera_id)
        uri = stream_uri_for(camera) if camera else None
    return camera, uri


def _rewrite_playlist_with_auth(playlist_text: str, *, base_url: str, camera_id: int, api_key_value: str | None) -> str:
    # ffmpeg's HLS muxer writes bare segment filenames (e.g. "segment000.ts"),
    # relative to the playlist's own URL. A player resolving that relative
    # reference does NOT carry the playlist URL's own query string forward
    # (RFC 3986 5.3), so the ?api_key=... on the /index.m3u8 request is
    # silently dropped from every subsequent segment fetch, and Home
    # Assistant's stream integration (which has no way to attach a custom
    # header per segment) gets 401s and never plays anything. Rewriting each
    # segment reference into a full, self-authenticating URL fixes that.
    if not api_key_value:
        return playlist_text
    rewritten_lines = []
    for line in playlist_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            rewritten_lines.append(
                f"{base_url}/api/v1/cameras/{camera_id}/stream/{stripped}?api_key={api_key_value}"
            )
        else:
            rewritten_lines.append(line)
    return "\n".join(rewritten_lines) + "\n"


async def _poll_loop() -> None:
    await asyncio.sleep(5)
    while True:
        try:
            for camera in database.list_cameras(SETTINGS.database_path):
                if int(camera.get("enabled") or 0) != 1:
                    continue
                try:
                    await _refresh_camera(int(camera["id"]))
                except Exception:
                    LOGGER.exception("Background refresh failed for camera %s", camera.get("id"))
            for account in database.list_network_accounts(SETTINGS.database_path):
                if int(account.get("enabled") or 0) != 1:
                    continue
                try:
                    await _publish_network_state(int(account["id"]))
                except Exception:
                    LOGGER.exception("Background refresh failed for network account %s", account.get("id"))
        except Exception:
            LOGGER.exception("Background camera refresh failed")
        await asyncio.sleep(SETTINGS.poll_interval_seconds)


async def _camera_event_supervisor() -> None:
    """Keep one real-time event connection per enabled camera whose plugin provides one."""
    workers: dict[int, tuple[tuple[Any, ...], asyncio.Task[Any]]] = {}
    await asyncio.sleep(2)
    try:
        while True:
            cameras: dict[int, dict[str, Any]] = {}
            for camera in database.list_cameras(SETTINGS.database_path):
                if int(camera.get("enabled") or 0) != 1:
                    continue
                try:
                    module = get_camera_module(camera.get("module_key"))
                except UnknownCameraModuleError:
                    continue
                if _event_monitor_for_module(module) is not None:
                    cameras[int(camera["id"])] = camera
            for camera_id, (_, task) in list(workers.items()):
                camera = cameras.get(camera_id)
                fingerprint = _event_connection_fingerprint(camera) if camera else None
                if task.done() or fingerprint != workers[camera_id][0]:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    workers.pop(camera_id, None)
            for camera_id, camera in cameras.items():
                if camera_id not in workers:
                    workers[camera_id] = (
                        _event_connection_fingerprint(camera),
                        asyncio.create_task(_monitor_camera_events(camera_id)),
                    )
            await asyncio.sleep(10)
    finally:
        for _, task in workers.values():
            task.cancel()
        if workers:
            await asyncio.gather(*(task for _, task in workers.values()), return_exceptions=True)


def _event_connection_fingerprint(camera: dict[str, Any] | None) -> tuple[Any, ...]:
    if camera is None:
        return ()
    return (
        camera.get("module_key"),
        camera.get("host"),
        camera.get("http_port"),
        camera.get("username"),
        camera.get("password"),
    )


def _event_monitor_for_module(module: Any):
    monitor = getattr(module, "monitor_events", None)
    if callable(monitor):
        return monitor
    module_package = module.__class__.__module__.rpartition(".")[0]
    if not module_package:
        return None
    try:
        service = importlib.import_module(f"{module_package}.service")
    except (ImportError, ValueError):
        return None
    monitor = getattr(service, "monitor_events", None)
    return monitor if callable(monitor) else None


async def _monitor_camera_events(camera_id: int) -> None:
    while True:
        camera = database.get_camera(SETTINGS.database_path, camera_id)
        if camera is None or int(camera.get("enabled") or 0) != 1:
            return
        try:
            module = get_camera_module(camera.get("module_key"))
        except UnknownCameraModuleError:
            return
        monitor_events = _event_monitor_for_module(module)
        if monitor_events is None:
            return
        try:
            await monitor_events(
                camera,
                lambda detections: _process_detection_states(camera_id, detections),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("Real-time events unavailable for camera %s: %s", camera_id, exc)
            await asyncio.sleep(15)


async def _plugin_source_update_check_loop() -> None:
    await asyncio.sleep(30)
    while True:
        try:
            for source in database.list_plugin_sources(SETTINGS.database_path):
                await _check_plugin_source_for_update(source)
        except Exception:
            LOGGER.exception("Prüfung auf Plugin-Updates fehlgeschlagen")
        await asyncio.sleep(PLUGIN_SOURCE_UPDATE_CHECK_INTERVAL_SECONDS)


async def _app_update_check_loop() -> None:
    await asyncio.sleep(30)
    while True:
        try:
            release = await asyncio.to_thread(fetch_latest_release)
            APP_UPDATE_STATE.update(
                latest_version=release.version,
                update_available=is_newer(release.version, __version__),
                html_url=release.html_url,
                checked_at=datetime.utcnow().isoformat(timespec="seconds"),
                error=None,
            )
        except AppUpdateCheckError as exc:
            APP_UPDATE_STATE.update(error=str(exc), checked_at=datetime.utcnow().isoformat(timespec="seconds"))
        except Exception:
            LOGGER.exception("Prüfung auf TBC-Updates fehlgeschlagen")
        await asyncio.sleep(APP_UPDATE_CHECK_INTERVAL_SECONDS)


async def _check_plugin_source_for_update(source: dict[str, Any]) -> None:
    try:
        github_repo = parse_github_repo_url(source["repo_url"])
        latest_sha = await asyncio.to_thread(
            fetch_latest_commit_sha, github_repo.owner, github_repo.repo, source["ref"]
        )
    except Exception as exc:
        LOGGER.info("Update-Prüfung für Quelle %s (%s) fehlgeschlagen: %s", source["id"], source["label"], exc)
        return
    installed_sha = source.get("installed_ref_sha")
    update_available = bool(installed_sha) and installed_sha != latest_sha
    database.update_plugin_source_check_result(
        SETTINGS.database_path,
        source["id"],
        latest_ref_sha=latest_sha,
        update_available=update_available,
    )


async def _snapshot_loop() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            cameras_with_stream = [
                camera
                for camera in database.list_cameras(SETTINGS.database_path)
                if int(camera.get("enabled") or 0) == 1 and stream_uri_for(camera)
            ]

            async def refresh(camera: dict[str, Any]) -> None:
                async with SNAPSHOT_SEMAPHORE:
                    await asyncio.to_thread(
                        SNAPSHOT_MANAGER.refresh_if_due,
                        int(camera["id"]),
                        str(stream_uri_for(camera)),
                    )

            await asyncio.gather(*(refresh(camera) for camera in cameras_with_stream))
        except Exception:
            LOGGER.exception("Dashboard-Snapshots konnten nicht aktualisiert werden")
        await asyncio.sleep(60)


async def _health_loop() -> None:
    await asyncio.sleep(15)
    last_health_event_id = _latest_health_event_id()
    first_run = True
    while True:
        try:
            await asyncio.to_thread(run_health_checks, SETTINGS.database_path)
            new_events = [
                event
                for event in database.list_health_events(SETTINGS.database_path, limit=50)
                if int(event["id"]) > last_health_event_id
            ]
            if new_events:
                last_health_event_id = max(int(event["id"]) for event in new_events)
                if not first_run:
                    _notify_health_events(new_events)
            first_run = False
        except Exception:
            LOGGER.exception("Health checks failed")
        await asyncio.sleep(300)


async def _cleanup_loop() -> None:
    await asyncio.sleep(60)
    while True:
        try:
            deleted = await asyncio.to_thread(apply_cleanup, SETTINGS.database_path)
            if deleted:
                notify_event(
                    SETTINGS.database_path,
                    event_type="cleanup_finished",
                    title="TBC: Cleanup",
                    message=f"{deleted} clips were deleted by retention",
                    public_base_url=SETTINGS.public_base_url,
                )
        except Exception:
            LOGGER.exception("Retention cleanup failed")
        await asyncio.sleep(3600)


async def _continuous_recording_loop() -> None:
    await asyncio.sleep(8)
    while True:
        try:
            cameras = database.list_cameras(SETTINGS.database_path)
            await asyncio.to_thread(CONTINUOUS_RECORDING_MANAGER.sync, cameras)
        except Exception:
            LOGGER.exception("Continuous recording sync failed")
        await asyncio.sleep(20)


class InvalidSessionError(Exception):
    """The session cookie looks logged-in, but its user_id has no matching row.

    Happens whenever a session outlives the account it points at - the account
    was deleted, or the database was restored from a backup that predates it.
    Every _current_user() caller assumes a valid dict comes back and does not
    catch this itself, so the global handler below (registered on `app`) is
    what actually turns this into a clean re-login instead of an unhandled 500.
    """


def _is_logged_in(request: Request) -> bool:
    return bool(request.session.get("user_id"))


def _current_user(request: Request) -> dict[str, Any]:
    user_id = request.session.get("user_id")
    if not user_id:
        raise InvalidSessionError("not logged in")
    user = database.get_user(SETTINGS.database_path, int(user_id))
    if user is None:
        request.session.clear()
        raise InvalidSessionError("session user does not exist")
    request.session["username"] = user["username"]
    request.session["role"] = user["role"]
    return user


@app.exception_handler(InvalidSessionError)
async def _invalid_session_error_handler(request: Request, exc: InvalidSessionError):
    request.session.clear()
    if request.url.path.startswith(("/api/", "/mcp")):
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    return _redirect("/login")


def _require_login(request: Request):
    if not _is_logged_in(request):
        return _redirect("/login")
    return None


def _require_admin(request: Request):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    if user.get("role") != "admin":
        _set_flash(request, "common.admin_required", None, "error")
        return _redirect("/cameras")
    return None


def _stash_api_token(request: Request, token: dict[str, Any]) -> None:
    request.state.api_token = token
    database.touch_api_token_last_used(SETTINGS.database_path, int(token["id"]))


def _require_api_key(request: Request) -> JSONResponse | None:
    config = database.get_api_config(SETTINGS.database_path)
    error = api_auth_error(
        config,
        request.headers.get("Authorization"),
        request.headers.get("X-API-Key"),
        find_token=lambda prefix: database.find_active_api_token_by_prefix(SETTINGS.database_path, prefix),
        on_success=lambda token: _stash_api_token(request, token),
    )
    if error:
        code, message = error
        return JSONResponse({"error": message}, status_code=code)
    return None


def _require_api_key_control(request: Request) -> JSONResponse | None:
    guard = _require_api_key(request)
    if guard:
        return guard
    token = getattr(request.state, "api_token", None)
    if not token or not token["can_control"]:
        return JSONResponse({"error": "this API token does not have control (write) access"}, status_code=status.HTTP_403_FORBIDDEN)
    return None


def _api_token_username(request: Request) -> str | None:
    token = getattr(request.state, "api_token", None)
    return f"api-token:{token['name']}" if token else None


def _detection_settings_public_dict(settings: dict[str, Any], camera_id: int) -> dict[str, Any]:
    return {
        "camera_id": camera_id,
        "enabled": bool(settings.get("enabled")),
        "backend": settings.get("backend"),
        "confidence_threshold": settings.get("confidence_threshold"),
        "sample_fps": settings.get("sample_fps"),
    }


def _require_camera_access(request: Request, camera_id: int):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    if not database.user_can_access_camera(SETTINGS.database_path, int(user["id"]), str(user["role"]), camera_id):
        _set_flash(request, "common.camera_forbidden", None, "error")
        return _redirect("/cameras")
    return None


def _authorized_recording(request: Request, recording_id: int) -> dict[str, Any] | None:
    guard = _require_login(request)
    if guard:
        return None
    recording = database.get_recording(SETTINGS.database_path, recording_id)
    if recording is None:
        return None
    user = _current_user(request)
    if not database.user_can_access_camera(
        SETTINGS.database_path,
        int(user["id"]),
        str(user["role"]),
        int(recording["camera_id"]),
    ):
        return None
    return recording


def _timeline_payload(request: Request, rows: Any) -> list[dict[str, Any]]:
    # Returned in a JSON API response too, not only rendered into a
    # template - the ingress middleware only rewrites response headers
    # (Location/Set-Cookie), so a JSON body value needs the prefix baked in
    # here instead (see _live_item_payload for the same pattern).
    prefix = request.state.ingress_prefix
    payload = []
    for row in rows:
        has_snapshot = bool(row.get("snapshot_path") or row.get("snapshot_remote_key"))
        payload.append(
            {
                "id": int(row["id"]),
                "start": row["started_at"],
                "end": row.get("ended_at") or row["started_at"],
                "duration": int(row.get("duration_seconds") or 0),
                "detection_key": row["detection_key"],
                "label": row["event_label"],
                "media_url": f"{prefix}/recordings/{row['id']}/media",
                "snapshot_url": f"{prefix}/recordings/{row['id']}/snapshot" if has_snapshot else None,
            }
        )
    return payload


def _require_live_key_access(request: Request, live_key: str):
    if live_key.startswith("camera-"):
        try:
            camera_id = int(live_key.split("-", 1)[1])
        except ValueError:
            return JSONResponse({"error": "invalid live key"}, status_code=status.HTTP_404_NOT_FOUND)
        return _require_camera_access(request, camera_id)
    if live_key.startswith("channel-"):
        try:
            channel_id = int(live_key.split("-", 1)[1])
        except ValueError:
            return JSONResponse({"error": "invalid live key"}, status_code=status.HTTP_404_NOT_FOUND)
        channel = database.get_camera_channel(SETTINGS.database_path, channel_id)
        if not channel:
            return JSONResponse({"error": "channel not found"}, status_code=status.HTTP_404_NOT_FOUND)
        return _require_camera_access(request, int(channel["camera_id"]))
    return JSONResponse({"error": "invalid live key"}, status_code=status.HTTP_404_NOT_FOUND)


def _control_ptz_supported(camera: dict[str, Any], camera_id: int, *, channel: int) -> bool:
    """Strict, probe-confirmed PTZ support: unlike CameraCapability.CONTROL (a coarse
    module-level flag also true for cameras that only offer floodlight/siren/etc.),
    this only reports true once a background control-state probe has actually
    confirmed the device itself has PTZ. If no probe result is cached yet, one is
    kicked off in the background (mirroring camera_detail's lazy-probe pattern) and
    this returns False for now; the next page load/poll picks up the fresh result.
    """
    if not _camera_supports(camera, CameraCapability.CONTROL):
        return False
    control_state = CONTROL_STATE_CACHE.get((camera_id, channel))
    if control_state is None:
        try:
            camera_module = get_camera_module(camera.get("module_key"))
        except UnknownCameraModuleError:
            return False
        _kick_off_control_probe(camera_id, camera, camera_module, channel=channel)
        return False
    return bool(control_state.get("ptz_supported"))


def _live_items_for_user(user: dict[str, Any]) -> list[dict[str, Any]]:
    cameras = database.list_cameras_for_user(SETTINGS.database_path, int(user["id"]), str(user["role"]))
    items: list[dict[str, Any]] = []
    for camera in cameras:
        if not _camera_supports(camera, CameraCapability.LIVE):
            continue
        camera_id = int(camera["id"])
        enabled_channels = [
            channel
            for channel in database.list_camera_channels(SETTINGS.database_path, camera_id)
            if int(channel.get("enabled") or 0) == 1
        ]
        if not enabled_channels:
            items.append(
                {
                    "key": f"camera-{camera_id}",
                    "name": str(camera["name"]),
                    "subtitle": str(camera.get("host") or ""),
                    "kind": "Camera",
                    "camera_id": camera_id,
                    "control_channel": 0,
                    "ptz_supported": _control_ptz_supported(camera, camera_id, channel=0),
                    "stream_uri": stream_uri_for(camera),
                }
            )
            continue
        # A device with exactly one enabled channel (most non-NVR cameras that
        # still report a "channel 0") only gets a single tile named after the
        # camera itself, not a separate "camera" tile plus a redundant
        # "Channel 1" tile showing the identical stream. Multi-channel NVRs still
        # get one tile per channel, each addressed by its real channel index
        # instead of a guessed channel=0 for PTZ.
        single_channel = len(enabled_channels) == 1
        for channel in enabled_channels:
            channel_id = int(channel["id"])
            channel_index = int(channel["channel_index"])
            items.append(
                {
                    "key": f"channel-{channel_id}",
                    "name": str(camera["name"]) if single_channel else str(channel.get("name") or f"Channel {channel_index + 1}"),
                    "subtitle": str(camera.get("host") or "") if single_channel else f"{camera['name']} · Channel {channel_index + 1}",
                    "kind": "Camera" if single_channel else "Channel",
                    "camera_id": camera_id,
                    "control_channel": channel_index,
                    "ptz_supported": _control_ptz_supported(camera, camera_id, channel=channel_index),
                    "stream_uri": stream_uri_for(camera, channel),
                }
            )
    layout = database.get_live_layout(SETTINGS.database_path)
    for index, item in enumerate(items):
        entry = layout.get(item["key"], {})
        item["column_span"] = int(entry.get("column_span", 1))
        item["row_span"] = int(entry.get("row_span", 1))
        # Ties (the common case: nothing customized yet) keep the original,
        # stable camera/channel order instead of being reshuffled by sort().
        item["sort_order"] = int(entry.get("sort_order", index))
    items.sort(key=lambda entry: entry["sort_order"])
    return items


def _live_item_for_key(user: dict[str, Any], live_key: str) -> dict[str, Any] | None:
    for item in _live_items_for_user(user):
        if item["key"] == live_key:
            return item
    return None


def _start_live_item(item: dict[str, Any]) -> None:
    stream_uri = item.get("stream_uri")
    if not stream_uri:
        LIVE_MANAGER.note(str(item["key"]), "No stream is known for live view")
        return
    try:
        LIVE_MANAGER.start(str(item["key"]), str(stream_uri))
    except Exception as exc:
        LOGGER.exception("Live stream %s could not be started", item["key"])
        LIVE_MANAGER.note(str(item["key"]), f"Live stream could not be started: {exc}")


def _live_item_payload(request: Request, item: dict[str, Any]) -> dict[str, Any]:
    live_key = str(item["key"])
    has_stream = bool(item.get("stream_uri"))
    live_status = LIVE_MANAGER.status(live_key) if has_stream else "missing"
    message = LIVE_MANAGER.message(live_key)
    if live_status == "running" and message.startswith("Starting live stream"):
        message = ""
    if not has_stream and not message:
        message = "No stream is known for live view"
    # These two URLs are returned in JSON API responses too, not only
    # rendered into a template - the ingress middleware only rewrites
    # response headers (Location/Set-Cookie), so a JSON body value needs the
    # prefix baked in here instead.
    prefix = request.state.ingress_prefix
    return {
        "key": live_key,
        "name": item["name"],
        "subtitle": item["subtitle"],
        "kind": item["kind"],
        "status": live_status,
        "message": message,
        "playlist_url": f"{prefix}/live/{live_key}/index.m3u8",
        "webrtc_available": has_stream and GO2RTC_MANAGER.status() == "running",
        "webrtc_offer_url": f"{prefix}/live/{live_key}/webrtc/offer",
        "camera_id": item.get("camera_id"),
        "control_channel": item.get("control_channel", 0),
        "ptz_supported": bool(item.get("ptz_supported")),
        "column_span": int(item.get("column_span", 1)),
        "row_span": int(item.get("row_span", 1)),
        "sort_order": int(item.get("sort_order", 0)),
    }


def _sd_card_recording_payload(request: Request, camera_id: int, row: dict[str, Any]) -> dict[str, Any]:
    prefix = request.state.ingress_prefix
    payload = dict(row)
    query = {
        "channel": row.get("channel", 0),
        "stream": row.get("stream") or "main",
        "source": row.get("source") or "",
        "start": row.get("start_id") or "",
        "end": row.get("end_id") or "",
    }
    payload["media_url"] = f"{prefix}/sd-card/{camera_id}/media?{urlencode({**query, 'embed': 1})}"
    payload["download_url"] = f"{prefix}/sd-card/{camera_id}/media?{urlencode({**query, 'download': 1})}"
    return payload


def _camera_supports(camera: dict[str, Any], capability: CameraCapability) -> bool:
    try:
        return get_camera_module(camera.get("module_key")).supports(capability)
    except UnknownCameraModuleError:
        return False


def _camera_module_selector_options() -> list[dict[str, Any]]:
    modules = list_camera_modules()
    options = [
        {
            "key": module.key,
            "label": module.label,
            "description": module.description,
            "installed": True,
            "install_url": "/plugin-sources",
            "default_onvif_port": module.default_onvif_port,
            "default_http_port": module.default_http_port,
            "default_rtsp_port": module.default_rtsp_port,
            "supports_manual_stream_uri": module.supports_manual_stream_uri,
            "requires_manual_stream_uri": module.requires_manual_stream_uri,
            "requires_credentials": module.requires_credentials,
            "identifier_label": module.identifier_label,
        }
        for module in modules
    ]
    candidates = list_uninstalled_plugin_candidates(
        "camera",
        (module.key for module in modules),
        database.list_plugin_sources(SETTINGS.database_path),
    )
    options.extend(
        {
            "key": candidate.key,
            "label": candidate.label,
            "description": candidate.description,
            "installed": False,
            "install_url": candidate.install_url,
            "default_onvif_port": 8000,
            "default_http_port": 80,
            "default_rtsp_port": 554,
            "supports_manual_stream_uri": False,
            "requires_manual_stream_uri": False,
            "requires_credentials": False,
            "identifier_label": None,
        }
        for candidate in candidates
    )
    return options


def _cloud_module_selector_options() -> list[dict[str, Any]]:
    registrations = list_cloud_module_registrations()
    options = [
        {
            "key": registration.module.key,
            "label": registration.module.label,
            "description": registration.module.description,
            "installed": True,
            "install_url": "/plugin-sources",
        }
        for registration in registrations
    ]
    candidates = list_uninstalled_plugin_candidates(
        "cloud",
        (registration.module.key for registration in registrations),
        database.list_plugin_sources(SETTINGS.database_path),
    )
    options.extend(
        {
            "key": candidate.key,
            "label": candidate.label,
            "description": candidate.description,
            "installed": False,
            "install_url": candidate.install_url,
        }
        for candidate in candidates
    )
    return options


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


def _safe_internal_path(path: str, fallback: str) -> str:
    """Return `path` if it's a same-site path, else `fallback` - guards the
    retry_url round-tripped through /plugin-requirements/confirm's query
    string and back against being turned into an open redirect."""
    if path.startswith("/") and not path.startswith("//") and "\\" not in path:
        return path
    return fallback


def _redirect_to_requirements_confirm(
    exc: MissingPluginRequirements, retry_url: str, *, source_id: int | None = None
) -> RedirectResponse:
    params: dict[str, Any] = {
        "requirements": list(exc.missing),
        "retry_url": retry_url,
        "label": exc.plugin_label,
        "plugin_kind": exc.plugin_kind,
        "module_key": exc.module_key,
    }
    if source_id is not None:
        params["source_id"] = source_id
    query = urlencode(params, doseq=True)
    return _redirect(f"/plugin-requirements/confirm?{query}")


def _plugin_has_tests(package: Any) -> bool:
    if package is None:
        return False
    tests_dir = package.path / "tests"
    return tests_dir.is_dir() and any(tests_dir.glob("test_*.py"))


def _install_plugin_for_kind(plugin_kind: str, archive: bytes) -> str:
    """Install a fetched plugin archive into the given plugin kind's registry, returning the installed key."""
    if plugin_kind == "camera":
        package = install_plugin_archive(archive, SETTINGS.camera_modules_path)
        reload_camera_modules()
        return package.manifest.key
    if plugin_kind == "cloud":
        package = install_cloud_plugin_archive(archive, SETTINGS.cloud_modules_path)
        reload_cloud_modules()
        return package.manifest.key
    if plugin_kind == "network":
        package = install_network_plugin_archive(archive, SETTINGS.network_modules_path)
        reload_network_modules()
        return package.manifest.key
    if plugin_kind == "design":
        package = install_theme_archive(archive, SETTINGS.theme_modules_path)
        reload_themes()
        return package.manifest.key
    raise ValueError(f"Unbekannte Plugin-Art: {plugin_kind}")


def _clear_transient_cloud_account_fields(account_id: int, cloud_module: Any) -> None:
    keys = tuple(field.key for field in cloud_module.account_fields if field.transient)
    if keys:
        database.clear_cloud_account_configuration_fields(
            SETTINGS.database_path, account_id, keys
        )


async def _perform_cloud_account_login_attempt(
    request: Request,
    account_id: int,
    cloud_module: Any,
    account: dict[str, Any],
    *,
    success_redirect: str,
) -> Any:
    """Run test_connection() and translate the outcome into a redirect.

    Shared by the plain "Test connection" action and the verification-code
    submission, since both are just different ways of retrying the same
    login attempt - a CloudVerificationRequired here always means routing the
    admin to the dedicated /verify page instead of a plain error redirect.
    """
    try:
        message = await asyncio.wait_for(cloud_module.test_connection(account), timeout=CONTROL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        message = f"Connection did not respond within {CONTROL_TIMEOUT_SECONDS}s"
        database.update_cloud_account_test_result(SETTINGS.database_path, account_id, status="error", message=message)
        _set_flash(request, "common.raw_message", {"message": message}, "error")
        return _redirect(success_redirect)
    except CloudVerificationRequired as exc:
        database.set_cloud_account_pending_verification(
            SETTINGS.database_path, account_id, field_key=exc.field_key, message=str(exc)
        )
        database.update_cloud_account_test_result(SETTINGS.database_path, account_id, status="error", message=str(exc))
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/cloud-accounts/{account_id}/verify")
    except CloudConnectionError as exc:
        database.update_cloud_account_test_result(SETTINGS.database_path, account_id, status="error", message=str(exc))
        _clear_transient_cloud_account_fields(account_id, cloud_module)
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(success_redirect)
    except Exception as exc:
        LOGGER.info("Cloud account test failed for %s: %s", account_id, exc)
        database.update_cloud_account_test_result(SETTINGS.database_path, account_id, status="error", message=str(exc))
        _set_flash(request, "connection.failed", {"error": exc}, "error")
        return _redirect(success_redirect)
    database.update_cloud_account_test_result(SETTINGS.database_path, account_id, status="ok", message=message)
    _clear_transient_cloud_account_fields(account_id, cloud_module)
    _set_flash(request, "common.raw_message", {"message": message})
    return _redirect(success_redirect)


def _set_flash(request: Request, key: str, params: dict[str, Any] | None = None, level: str = "success") -> None:
    request.session["flash"] = {"key": key, "params": params or {}, "level": level}


def _camera_form_error(request: Request, values: dict[str, Any], key: str, params: dict[str, Any] | None = None):
    return templates.TemplateResponse(
        request,
        "camera_form.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "flash": None,
            "values": values,
            "camera_module_options": _camera_module_selector_options(),
            "error": _t_en(key, **(params or {})),
            "error_key": key,
            "error_params": params or {},
        },
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _pop_flash(request: Request) -> dict[str, Any] | None:
    flash = request.session.get("flash")
    if flash is not None:
        request.session.pop("flash", None)
        flash = dict(flash)
        flash["text"] = _t_en(flash["key"], **flash.get("params", {}))
    return flash


def _t_en(key: str, /, **params: Any) -> str:
    template = _LOCALE_EN.get(key, key)
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        return template


def _none_if_blank(value: str) -> str | None:
    value = value.strip()
    return value or None


def _parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def _safe_header_filename(value: str) -> str:
    return value.replace("\\", "_").replace("/", "_").replace('"', "_") or "clip.mp4"


def _validated_storage_kind(kind: str) -> str:
    return "s3" if kind == "s3" else "local"


def _notification_form_values(
    name: str,
    kind: str,
    enabled: str | None,
    include_snapshot: str | None,
    event_filter: str,
    url: str,
    token: str,
    chat_id: str,
    email_to: str,
    email_from: str,
    smtp_host: str,
    smtp_port: str,
    smtp_username: str,
    smtp_password: str,
    ha_service: str,
) -> dict[str, Any]:
    return {
        "name": name.strip(),
        "kind": kind if kind in {"telegram", "email", "webhook", "pushover", "home_assistant", "ntfy", "gotify"} else "webhook",
        "enabled": enabled == "on",
        "include_snapshot": include_snapshot == "on",
        "event_filter": _none_if_blank(event_filter),
        "url": _none_if_blank(url),
        "token": _none_if_blank(token),
        "chat_id": _none_if_blank(chat_id),
        "email_to": _none_if_blank(email_to),
        "email_from": _none_if_blank(email_from),
        "smtp_host": _none_if_blank(smtp_host),
        "smtp_port": int(smtp_port) if smtp_port else None,
        "smtp_username": _none_if_blank(smtp_username),
        "smtp_password": _none_if_blank(smtp_password),
        "ha_service": _none_if_blank(ha_service),
    }


def _notification_event_templates_from_form(form: Any) -> list[dict[str, Any]]:
    enabled_events = set(form.getlist("event_enabled"))
    templates: list[dict[str, Any]] = []
    for event in database.notification_event_defaults():
        event_type = str(event["event_type"])
        templates.append(
            {
                "event_type": event_type,
                "enabled": event_type in enabled_events,
                "title_template": str(form.get(f"event_title_{event_type}") or "{{ title }}").strip(),
                "message_template": str(form.get(f"event_message_{event_type}") or "{{ message }}").strip(),
            }
        )
    return templates


def _notification_event_filter(templates: list[dict[str, Any]]) -> str | None:
    selected = [str(template["event_type"]) for template in templates if template.get("enabled")]
    return ",".join(selected) or None


def _latest_health_event_id() -> int:
    events = database.list_health_events(SETTINGS.database_path, limit=1)
    return int(events[0]["id"]) if events else 0


def _notify_health_events(events: list[dict[str, Any]]) -> None:
    for event in reversed(events):
        notify_event(
            SETTINGS.database_path,
            event_type="health_status_changed",
            title=f"TBC Health: {event['status']}",
            message=f"{event['component_type']} {event['component_id']}: {event.get('message') or ''}",
            public_base_url=SETTINGS.public_base_url,
        )


# --- Routers extracted to app/tbc/routers/ (see that package for the route
# bodies themselves) - imported and included here, at the very end of the
# file, so every main.py-level name they need (SETTINGS, templates, the
# recording/live/snapshot managers, the auth/flash/redirect helpers, ...)
# already exists on this module by the time their own `from ..main import
# (...)` statements run. ---
from .routers import (  # noqa: E402 - deliberately last, see comment above
    api_internal,
    api_v1,
    auth,
    cameras,
    cloud_accounts,
    detection_recognition,
    docs_health,
    live,
    mqtt as mqtt_router,  # `mqtt` itself is already bound above (paho-mqtt control listener module)
    network_accounts,
    notifications,
    plugins,
    recordings,
    retention,
    settings,
    storage,
    users,
)

app.include_router(api_internal.router)
app.include_router(api_v1.router)
app.include_router(auth.router)
app.include_router(cameras.router)
app.include_router(cloud_accounts.router)
app.include_router(detection_recognition.router)
app.include_router(docs_health.router)
app.include_router(live.router)
app.include_router(mqtt_router.router)
app.include_router(network_accounts.router)
app.include_router(notifications.router)
app.include_router(plugins.router)
app.include_router(recordings.router)
app.include_router(retention.router)
app.include_router(settings.router)
app.include_router(storage.router)
app.include_router(users.router)

