from __future__ import annotations

import asyncio
import importlib
import json
import logging
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, File, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, audit, backup, database, mqtt
from .licenses import THIRD_PARTY_LICENSES, list_plugin_licenses
from .api_common import (
    api_auth_error,
    camera_public_dict as _camera_public_dict,
    recording_public_dict as _recording_public_dict,
    storage_public_dict as _storage_public_dict,
)
from .app_updates import AppUpdateCheckError, fetch_latest_release, is_newer
from .camera_modules import (
    CameraCapability,
    get_camera_module,
    list_camera_module_registrations,
    list_camera_modules,
    reload_camera_modules,
)
from .camera_modules.packages import (
    CameraPluginError,
    export_plugin_archive,
    install_plugin_archive,
    remove_external_plugin,
)
from .camera_modules.detections import DetectionDefinition
from .camera_modules.registry import UnknownCameraModuleError
from .camera_modules.streams import validate_manual_stream_uri
from .channels import apply_channel_enabled_filter
from .cloud_modules import (
    CloudAccountFieldType,
    CloudAccountValidationError,
    CloudConnectionError,
    CloudVerificationRequired,
    get_cloud_module,
    list_cloud_module_registrations,
    normalize_account_configuration,
    reload_cloud_modules,
)
from .cloud_modules.packages import (
    CloudPluginError,
    export_plugin_archive as export_cloud_plugin_archive,
    install_plugin_archive as install_cloud_plugin_archive,
    remove_external_plugin as remove_external_cloud_plugin,
)
from .cloud_modules.registry import UnknownCloudModuleError
from .network_modules import (
    NetworkAccountFieldType,
    NetworkAccountValidationError,
    NetworkConnectionError,
    get_network_module,
    list_network_module_registrations,
    normalize_account_configuration as normalize_network_account_configuration,
    reload_network_modules,
)
from .network_modules.packages import (
    NetworkPluginError,
    export_plugin_archive as export_network_plugin_archive,
    install_plugin_archive as install_network_plugin_archive,
    remove_external_plugin as remove_external_network_plugin,
)
from .network_modules.registry import UnknownNetworkModuleError
from .config import load_settings
from .debug_log import clear_entries as clear_debug_log_entries
from .debug_log import install_debug_log, list_entries as list_debug_log_entries
from .detection import factory as detection_factory
from .detection.classes import DETECTION_KEY_LABELS, LOITERING_KEY_LABELS
from .detection.model_provisioning import ensure_default_coral_model, ensure_default_model
from .detection.plugin_models import resolve_plugin_model
from .detection.recognition import (
    FACE_TRIGGER_DETECTION_KEYS,
    PLATE_TRIGGER_DETECTION_KEYS,
    ensure_face_models,
    ensure_plate_models,
    get_face_recognizer,
    process_recognition,
)
from .detection.backend import Detection
from .detection.supervisor import detection_supervisor
from .health import current_system_usage, run_health_checks
from .go2rtc import Go2rtcManager
from .live import LiveManager, redact_rtsp_credentials, stream_uri_for
from .maintenance import apply_cleanup, cleanup_preview, storage_overview
from .mcp_server import build_mcp_app
from .plugin_sources import (
    STANDARD_PLUGIN_SOURCES,
    PluginSourceError,
    StandardPluginSource,
    fetch_latest_commit_sha,
    get_standard_plugin_source,
    github_repositories_match,
    list_uninstalled_plugin_candidates,
    parse_github_repo_url,
    resolve_and_fetch_plugin,
)
from .plugin_templates import (
    build_camera_plugin_template,
    build_cloud_plugin_template,
    build_design_theme_template,
    build_network_plugin_template,
)
from .plugin_testing import run_plugin_tests
from .notifications import notify_event
from .recording import ContinuousRecordingManager, RecordingManager, delete_recording_files, presigned_url
from .security import generate_api_key, hash_api_key
from .snapshots import DashboardSnapshotManager
from .template_filters import tojson_html_safe
from .themes import UnknownThemeError, get_theme_registration, list_theme_registrations, reload_themes
from .themes.packages import (
    ThemePackageError,
    export_theme_archive,
    install_theme_archive,
    remove_external_theme,
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

app = FastAPI(title="TBC - TB Camera")
app.add_middleware(
    SessionMiddleware,
    secret_key=SETTINGS.secret_key,
    same_site="lax",
    https_only=SETTINGS.cookie_secure,
)
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


templates = Jinja2Templates(
    directory=BASE_DIR / "templates",
    context_processors=[_active_theme_context, _pending_plugin_updates_context, _app_update_context],
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
# does not start - so it is opened/closed explicitly below in additional
# on_event handlers.
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


@app.on_event("startup")
async def _start_mcp_session_manager() -> None:
    await MCP_SESSION_MANAGER_CM.__aenter__()


@app.on_event("shutdown")
async def _stop_mcp_session_manager() -> None:
    await MCP_SESSION_MANAGER_CM.__aexit__(None, None, None)


LOCAL_AI_TRIGGER_DEFINITIONS = tuple(
    DetectionDefinition(key=key, label=label, category="ai")
    for key, label in {**DETECTION_KEY_LABELS, **LOITERING_KEY_LABELS}.items()
)
DETECTION_MODEL_PATH = Path(SETTINGS.detection_models_path) / "default.onnx"
DETECTION_MODEL_METADATA_PATH = Path(SETTINGS.detection_models_path) / "default.json"
DETECTION_CORAL_MODEL_PATH = Path(SETTINGS.detection_models_path) / "default_edgetpu.tflite"
DETECTION_CORAL_MODEL_METADATA_PATH = Path(SETTINGS.detection_models_path) / "default_edgetpu.json"
RECOGNITION_MODELS_DIR = Path(SETTINGS.detection_models_path)
RECOGNITION_SNAPSHOT_DIR = Path(SETTINGS.recordings_path) / "recognition-events"


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


@app.on_event("startup")
async def startup() -> None:
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
    if database.get_live_wall_settings(SETTINGS.database_path).get("webrtc_enabled"):
        asyncio.create_task(asyncio.to_thread(_start_go2rtc))


@app.on_event("shutdown")
async def _stop_go2rtc_on_shutdown() -> None:
    await asyncio.to_thread(GO2RTC_MANAGER.stop)


def _start_go2rtc() -> None:
    try:
        GO2RTC_MANAGER.start()
    except RuntimeError as exc:
        LOGGER.warning("WebRTC live view is enabled but could not start go2rtc: %s", exc)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "tbc"}


@app.get("/design/{theme_key}/static/{asset_path:path}", name="theme_asset")
async def theme_asset(theme_key: str, asset_path: str):
    try:
        registration = get_theme_registration(theme_key)
    except UnknownThemeError:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    relative = PurePosixPath(asset_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        return JSONResponse({"error": "invalid path"}, status_code=status.HTTP_400_BAD_REQUEST)
    file_path = registration.package.path / "static" / relative
    if not file_path.is_file():
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(file_path)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not _is_logged_in(request):
        return _redirect("/login")
    return _redirect("/cameras")


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if _is_logged_in(request):
        return _redirect("/cameras")
    return templates.TemplateResponse(
        request,
        "login.html",
        {"app_name": SETTINGS.app_name, "error": None, "flash": _pop_flash(request)},
    )


@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = database.authenticate_user(SETTINGS.database_path, username.strip(), password)
    if user is None:
        audit.log_event(request, SETTINGS.database_path, "auth.login_failed", username_override=username.strip())
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "app_name": SETTINGS.app_name,
                "error": _t_en("login.sign_in_failed"),
                "error_key": "login.sign_in_failed",
                "error_params": {},
                "flash": None,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["role"] = user.get("role", "admin")
    audit.log_event(request, SETTINGS.database_path, "auth.login_succeeded")
    return _redirect("/cameras")


@app.post("/logout")
async def logout(request: Request):
    if _is_logged_in(request):
        audit.log_event(request, SETTINGS.database_path, "auth.logout")
    request.session.clear()
    return _redirect("/login")


@app.get("/cameras", response_class=HTMLResponse)
async def cameras(request: Request):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    camera_rows = database.list_cameras_for_user(SETTINGS.database_path, int(user["id"]), str(user["role"]))
    for camera in camera_rows:
        camera["dashboard_snapshot_version"] = SNAPSHOT_MANAGER.version(int(camera["id"]))
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "cameras": camera_rows,
            "snapshot_interval_minutes": max(1, SETTINGS.dashboard_snapshot_interval_seconds // 60),
            "flash": _pop_flash(request),
        },
    )


@app.get("/cameras/new", response_class=HTMLResponse)
async def new_camera_choice(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "camera_new_choice.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "flash": _pop_flash(request),
        },
    )


@app.get("/cameras/new/local", response_class=HTMLResponse)
async def new_camera(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    user = _current_user(request)
    camera_module_options = _camera_module_selector_options()
    default_module_key = next(
        (option["key"] for option in camera_module_options if option["installed"]),
        "",
    )
    return templates.TemplateResponse(
        request,
        "camera_form.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "flash": _pop_flash(request),
            "values": {
                "module_key": default_module_key,
                "name": "",
                "host": "",
                "onvif_port": 8000,
                "http_port": 80,
                "rtsp_port": 554,
                "username": "",
                "manual_stream_uri": "",
            },
            "camera_module_options": camera_module_options,
            "error": None,
        },
    )


@app.post("/cameras", response_class=HTMLResponse)
async def create_camera(
    request: Request,
    name: str = Form(...),
    host: str = Form(""),
    onvif_port: int = Form(8000),
    http_port: int = Form(80),
    rtsp_port: int = Form(554),
    username: str = Form(""),
    password: str = Form(""),
    module_key: str = Form("standard_onvif"),
    manual_stream_uri: str = Form(""),
):
    guard = _require_admin(request)
    if guard:
        return guard

    values = {
        "module_key": module_key.strip().lower(),
        "name": name.strip(),
        "host": host.strip(),
        "onvif_port": onvif_port,
        "http_port": http_port,
        "rtsp_port": rtsp_port,
        "username": username.strip(),
        # Never echo a credential-bearing URI back into rendered HTML.
        "manual_stream_uri": "",
    }
    try:
        camera_module = get_camera_module(values["module_key"])
    except UnknownCameraModuleError as exc:
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
                "error": _t_en("common.raw_message", message=str(exc)),
                "error_key": "common.raw_message",
                "error_params": {"message": str(exc)},
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        normalized_manual_uri = (
            validate_manual_stream_uri(manual_stream_uri)
            if manual_stream_uri.strip()
            else None
        )
    except ValueError as exc:
        return _camera_form_error(request, values, "common.raw_message", {"message": str(exc)})
    if normalized_manual_uri and not camera_module.supports_manual_stream_uri:
        return _camera_form_error(request, values, "camera.module_no_manual_stream", {"label": camera_module.label})
    if camera_module.requires_manual_stream_uri and not normalized_manual_uri:
        return _camera_form_error(request, values, "camera.rtsp_url_required")
    if not values["host"] and normalized_manual_uri:
        values["host"] = str(urlsplit(normalized_manual_uri).hostname or "")
    credentials_missing = camera_module.requires_credentials and (not values["username"] or not password)
    if not values["name"] or not values["host"] or credentials_missing:
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
                "error": _t_en("camera.name_host_credentials_required"),
                "error_key": "camera.name_host_credentials_required",
                "error_params": {},
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    camera_id = database.create_camera(
        SETTINGS.database_path,
        name=values["name"],
        host=values["host"],
        onvif_port=int(onvif_port),
        http_port=int(http_port),
        username=values["username"],
        password=password,
        module_key=values["module_key"],
        rtsp_port=max(1, min(65535, int(rtsp_port))),
        manual_stream_uri=normalized_manual_uri,
    )
    await _refresh_camera(camera_id)
    audit.log_event(request, SETTINGS.database_path, "camera.created", target_type="camera", target_id=camera_id, detail={"name": values["name"], "module_key": values["module_key"]})
    _set_flash(request, "camera.created_and_checked")
    return _redirect(f"/cameras/{camera_id}")


@app.get("/cameras/{camera_id}", response_class=HTMLResponse)
async def camera_detail(
    request: Request,
    camera_id: int,
    control_channel: int | None = Query(None),
    network_account_id: int | None = Query(None),
):
    guard = _require_camera_access(request, camera_id)
    if guard:
        return guard
    user = _current_user(request)
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        _set_flash(request, "camera.not_found", None, "error")
        return _redirect("/cameras")
    detections = database.list_detections(SETTINGS.database_path, camera_id)
    storage_targets = database.list_storage_targets(SETTINGS.database_path)
    events = database.list_recent_events(SETTINGS.database_path, camera_id)
    active_trigger_keys = database.list_camera_recording_triggers(SETTINGS.database_path, camera_id) or ["motion"]
    channels = database.list_camera_channels(SETTINGS.database_path, camera_id)
    try:
        camera_module = get_camera_module(camera.get("module_key"))
    except UnknownCameraModuleError:
        camera_module = None
    camera_module_registration = next(
        (item for item in list_camera_module_registrations() if item.module.key == camera.get("module_key")),
        None,
    )
    recent_clips = database.list_recordings(SETTINGS.database_path, camera_id=camera_id, limit=4)
    module_capabilities = {capability.value for capability in camera_module.capabilities} if camera_module else set()
    available_triggers = camera_module.detection_definitions() if camera_module else ()
    detection_settings = database.get_camera_detection_settings(SETTINGS.database_path, camera_id)
    detection_zones = database.list_camera_detection_zones(SETTINGS.database_path, camera_id)
    local_ai_enabled = bool(detection_settings and detection_settings.get("enabled"))
    if camera.get("stream_uri") or local_ai_enabled:
        existing_trigger_keys = {trigger.key for trigger in available_triggers}
        available_triggers = tuple(available_triggers) + tuple(
            trigger for trigger in LOCAL_AI_TRIGGER_DEFINITIONS if trigger.key not in existing_trigger_keys
        )
    control_channel_options = [int(channel["channel_index"]) for channel in channels]
    selected_control_channel = (
        control_channel
        if control_channel is not None and control_channel in control_channel_options
        else (control_channel_options[0] if control_channel_options else 0)
    )
    control_live_key = next(
        (
            f"channel-{int(channel['id'])}"
            for channel in channels
            if int(channel["channel_index"]) == selected_control_channel
        ),
        f"camera-{camera_id}",
    )
    control_state = None
    if camera_module and camera_module.supports(CameraCapability.CONTROL):
        control_state = CONTROL_STATE_CACHE.get((camera_id, selected_control_channel))
        if control_state is None:
            # First view of this channel before any probe cycle has populated the
            # cache: kick off a background fetch instead of blocking this request
            # on a live device round-trip, which can take many seconds for an
            # unreachable/slow camera. The page renders immediately with a
            # "status unknown" fallback and picks up fresh data on next visit.
            _kick_off_control_probe(camera_id, camera, camera_module, channel=selected_control_channel)
    network_accounts = database.list_network_accounts(SETTINGS.database_path)
    network_state = None
    if camera.get("network_account_id") and camera.get("network_device_mac"):
        cached_devices = NETWORK_STATE_CACHE.get(int(camera["network_account_id"]))
        if cached_devices is None:
            _kick_off_network_probe(int(camera["network_account_id"]))
        else:
            network_state = next(
                (
                    device
                    for device in cached_devices
                    if str(device["mac_address"]).strip().lower() == camera["network_device_mac"]
                ),
                None,
            )
    # Populated only when the admin explicitly opens the device picker
    # (?network_account_id=...) - unlike network_state above, this is a
    # deliberate on-demand action, not something every page view should pay
    # the cost of, so it calls the controller synchronously with a timeout
    # instead of going through the background cache.
    network_picker_devices: list[dict[str, Any]] = []
    network_picker_error: str | None = None
    if network_account_id is not None:
        picker_account = database.get_network_account(SETTINGS.database_path, network_account_id)
        if picker_account is None:
            network_picker_error = _t_en("network_account.not_found")
        else:
            try:
                network_module = get_network_module(picker_account["module_key"])
            except UnknownNetworkModuleError as exc:
                network_picker_error = str(exc)
            else:
                try:
                    devices = await asyncio.wait_for(
                        network_module.discover_devices(picker_account), timeout=CONTROL_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    network_picker_error = _t_en("network_account.discovery_timeout", seconds=CONTROL_TIMEOUT_SECONDS)
                except NetworkConnectionError as exc:
                    network_picker_error = str(exc)
                except Exception as exc:
                    LOGGER.info("Network device picker failed for account %s: %s", network_account_id, exc)
                    network_picker_error = str(exc)
                else:
                    network_picker_devices = [_network_device_to_dict(device) for device in devices]
                    NETWORK_STATE_CACHE[network_account_id] = network_picker_devices
    return templates.TemplateResponse(
        request,
        "camera_detail.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "camera": camera,
            "detections": detections,
            "storage_targets": storage_targets,
            "events": events,
            "channels": channels,
            "camera_module": camera_module,
            "camera_module_registration": camera_module_registration,
            "recent_clips": recent_clips,
            "module_capabilities": module_capabilities,
            "available_triggers": available_triggers,
            "trigger_labels": {trigger.key: trigger.label for trigger in available_triggers},
            "active_trigger_keys": active_trigger_keys,
            "detection_settings": detection_settings,
            "local_ai_enabled": local_ai_enabled,
            "detection_default_sample_fps": SETTINGS.detection_default_sample_fps,
            "detection_default_confidence_threshold": SETTINGS.detection_default_confidence_threshold,
            "detection_backend_status": detection_factory.backend_status(),
            "detection_backend_labels": detection_factory.BACKEND_LABELS,
            "detection_zones": detection_zones,
            "detection_key_labels": DETECTION_KEY_LABELS,
            "control_state": control_state,
            "control_channel_options": control_channel_options,
            "selected_control_channel": selected_control_channel,
            "control_live_key": control_live_key,
            "network_accounts": network_accounts,
            "network_state": network_state,
            "network_picker_account_id": network_account_id,
            "network_picker_devices": network_picker_devices,
            "network_picker_error": network_picker_error,
            "flash": _pop_flash(request),
        },
    )


@app.post("/cameras/{camera_id}/network")
async def set_camera_network_mapping_route(
    request: Request,
    camera_id: int,
    network_account_id: int = Form(...),
    mac: str = Form(...),
):
    guard = _require_admin(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        _set_flash(request, "camera.not_found", None, "error")
        return _redirect("/cameras")
    if not mac.strip():
        _set_flash(request, "network_account.select_device_required", None, "error")
        return _redirect(f"/cameras/{camera_id}?network_account_id={network_account_id}#network")
    database.set_camera_network_mapping(
        SETTINGS.database_path, camera_id, network_account_id=network_account_id, mac=mac
    )
    _kick_off_network_probe(network_account_id)
    _set_flash(request, "network_account.camera_mapped")
    return _redirect(f"/cameras/{camera_id}#network")


@app.post("/cameras/{camera_id}/network/unlink")
async def clear_camera_network_mapping_route(request: Request, camera_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.clear_camera_network_mapping(SETTINGS.database_path, camera_id)
    _set_flash(request, "network_account.camera_unmapped")
    return _redirect(f"/cameras/{camera_id}#network")


@app.get("/cameras/{camera_id}/snapshot.jpg")
async def dashboard_camera_snapshot(request: Request, camera_id: int):
    guard = _require_camera_access(request, camera_id)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    stream_uri = stream_uri_for(camera) if camera else None
    if not stream_uri:
        return JSONResponse({"error": "snapshot not available"}, status_code=status.HTTP_404_NOT_FOUND)
    async with SNAPSHOT_SEMAPHORE:
        snapshot_path = await asyncio.to_thread(
            SNAPSHOT_MANAGER.refresh_if_due,
            camera_id,
            stream_uri,
        )
    if snapshot_path is None or not snapshot_path.exists():
        return JSONResponse({"error": "snapshot not available"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(
        snapshot_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store, max-age=0"},
    )


@app.get("/api/cameras/{camera_id}/detections")
async def camera_detections_api(request: Request, camera_id: int):
    guard = _require_camera_access(request, camera_id)
    if guard:
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return {"camera_id": camera_id, "detections": database.list_detections(SETTINGS.database_path, camera_id)}


@app.post("/cameras/{camera_id}/refresh")
async def refresh_camera(request: Request, camera_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        _set_flash(request, "camera.not_found", None, "error")
        return _redirect("/cameras")
    try:
        snapshot = await _refresh_camera(camera_id)
    except UnknownCameraModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/cameras/{camera_id}")
    _set_flash(request, "common.raw_message", {"message": snapshot.message})
    return _redirect(f"/cameras/{camera_id}")


@app.post("/cameras/{camera_id}/control/ptz")
async def control_camera_ptz(
    request: Request,
    camera_id: int,
    command: str = Form(""),
    speed: str = Form(""),
    preset: str = Form(""),
    channel: int = Form(0),
):
    params: dict[str, Any] = {}
    if preset.strip():
        params["preset"] = preset.strip()
    elif command.strip():
        params["command"] = command.strip()
    if speed.strip():
        try:
            params["speed"] = int(speed)
        except ValueError:
            pass
    return await _execute_control(request, camera_id, action="ptz", params=params, channel=channel)


@app.post("/cameras/{camera_id}/control/floodlight")
async def control_camera_floodlight(
    request: Request, camera_id: int, state: str | None = Form(None), channel: int = Form(0)
):
    return await _execute_control(
        request, camera_id, action="floodlight", params={"state": state == "on"}, channel=channel
    )


@app.post("/cameras/{camera_id}/control/pir")
async def control_camera_pir(
    request: Request, camera_id: int, enable: str | None = Form(None), channel: int = Form(0)
):
    return await _execute_control(
        request, camera_id, action="pir", params={"enable": enable == "on"}, channel=channel
    )


@app.post("/cameras/{camera_id}/control/siren")
async def control_camera_siren(request: Request, camera_id: int, duration: int = Form(5), channel: int = Form(0)):
    return await _execute_control(
        request, camera_id, action="siren", params={"duration": duration}, channel=channel
    )


@app.post("/cameras/{camera_id}/control/reboot")
async def control_camera_reboot(request: Request, camera_id: int, channel: int = Form(0)):
    return await _execute_control(request, camera_id, action="reboot", params={}, channel=channel)


@app.post("/cameras/{camera_id}/control/zoom")
async def control_camera_zoom(request: Request, camera_id: int, position: int = Form(...), channel: int = Form(0)):
    return await _execute_control(request, camera_id, action="zoom", params={"position": position}, channel=channel)


@app.post("/cameras/{camera_id}/control/focus")
async def control_camera_focus(request: Request, camera_id: int, position: int = Form(...), channel: int = Form(0)):
    return await _execute_control(request, camera_id, action="focus", params={"position": position}, channel=channel)


@app.post("/cameras/{camera_id}/control/quick-reply")
async def control_camera_quick_reply(request: Request, camera_id: int, file_id: int = Form(...), channel: int = Form(0)):
    return await _execute_control(
        request, camera_id, action="quick_reply", params={"file_id": file_id}, channel=channel
    )


@app.post("/cameras/{camera_id}/firmware/check")
async def check_camera_firmware(request: Request, camera_id: int, channel: int = Form(0)):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    camera, camera_module, error = _firmware_camera_and_module(camera_id)
    if error:
        return error
    key = (camera_id, channel)
    FIRMWARE_UPDATE_STATE[key] = {"status": "checking", "progress": 0, "message": ""}
    try:
        result = await asyncio.wait_for(
            camera_module.check_firmware(camera, channel=channel), timeout=CONTROL_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        FIRMWARE_UPDATE_STATE[key] = {"status": "failed", "progress": 0, "message": "Firmware check timed out"}
        return JSONResponse({"ok": False, "message": "Firmware check timed out"}, status_code=status.HTTP_504_GATEWAY_TIMEOUT)
    except Exception as exc:
        FIRMWARE_UPDATE_STATE[key] = {"status": "failed", "progress": 0, "message": str(exc)}
        return JSONResponse({"ok": False, "message": f"Check failed: {exc}"}, status_code=status.HTTP_502_BAD_GATEWAY)
    FIRMWARE_UPDATE_STATE[key] = {
        "status": "available" if result.get("update_available") else "up_to_date",
        "progress": 0,
        "message": "",
        **result,
    }
    return {"ok": True, **result}


@app.post("/cameras/{camera_id}/firmware/update")
async def start_camera_firmware_update(request: Request, camera_id: int, channel: int = Form(0)):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    camera, camera_module, error = _firmware_camera_and_module(camera_id)
    if error:
        return error
    key = (camera_id, channel)
    current = FIRMWARE_UPDATE_STATE.get(key)
    if not current or not current.get("update_available"):
        return JSONResponse(
            {"ok": False, "message": "Check for updates first"}, status_code=status.HTTP_400_BAD_REQUEST
        )
    if current.get("status") == "updating":
        return JSONResponse({"ok": False, "message": "An update is already running"}, status_code=status.HTTP_409_CONFLICT)
    FIRMWARE_UPDATE_STATE[key] = {**current, "status": "updating", "progress": 0, "message": "Update wird gestartet…"}
    asyncio.create_task(_run_firmware_update_task(camera_id, camera, camera_module, channel))
    return {"ok": True, "message": "Firmware-Update gestartet"}


@app.get("/cameras/{camera_id}/firmware/status")
async def camera_firmware_status(request: Request, camera_id: int, channel: int = Query(0)):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    state = FIRMWARE_UPDATE_STATE.get((camera_id, channel), {"status": "idle", "progress": 0, "message": ""})
    return {"ok": True, **state}


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
    finally:
        NETWORK_STATE_PROBES_IN_FLIGHT.discard(network_account_id)


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


@app.post("/cameras/{camera_id}/recording")
async def update_camera_recording(
    request: Request,
    camera_id: int,
    recording_duration_seconds: int = Form(30),
    recording_pre_seconds: int = Form(0),
    recording_post_seconds: int = Form(10),
    recording_cooldown_seconds: int = Form(90),
    recording_storage_id: str = Form(""),
    recording_enabled: str | None = Form(None),
    snapshot_enabled: str | None = Form(None),
    trigger_keys: list[str] = Form([]),
):
    guard = _require_admin(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        _set_flash(request, "camera.not_found", None, "error")
        return _redirect("/cameras")
    try:
        camera_module = get_camera_module(camera.get("module_key"))
    except UnknownCameraModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/cameras/{camera_id}")
    detection_settings = database.get_camera_detection_settings(SETTINGS.database_path, camera_id)
    local_ai_enabled = bool(detection_settings and detection_settings.get("enabled"))
    if not local_ai_enabled and not camera_module.supports(CameraCapability.RECORDING):
        _set_flash(request, "camera.module_no_event_recording", {"label": camera_module.label}, "error")
        return _redirect(f"/cameras/{camera_id}")
    storage_id = int(recording_storage_id) if recording_storage_id else None
    database.update_camera_recording_settings(
        SETTINGS.database_path,
        camera_id,
        recording_enabled=recording_enabled == "on",
        recording_duration_seconds=max(5, min(3600, int(recording_duration_seconds))),
        recording_pre_seconds=max(0, min(120, int(recording_pre_seconds))),
        recording_post_seconds=max(0, min(600, int(recording_post_seconds))),
        recording_cooldown_seconds=max(0, min(86400, int(recording_cooldown_seconds))),
        snapshot_enabled=snapshot_enabled == "on",
        recording_storage_id=storage_id,
        trigger_keys=trigger_keys or ["motion"],
    )
    _set_flash(request, "recording.event_settings_saved")
    return _redirect(f"/cameras/{camera_id}")


@app.post("/cameras/{camera_id}/detection")
async def update_camera_detection(
    request: Request,
    camera_id: int,
    detection_confidence_threshold: float = Form(0.5),
    detection_sample_fps: float = Form(2.0),
    detection_enabled: str | None = Form(None),
    detection_backend: str = Form("cpu"),
):
    guard = _require_admin(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        _set_flash(request, "camera.not_found", None, "error")
        return _redirect("/cameras")
    backend = detection_backend if detection_backend in detection_factory.BACKEND_CHOICES else "cpu"
    database.update_camera_detection_settings(
        SETTINGS.database_path,
        camera_id,
        enabled=detection_enabled == "on",
        backend=backend,
        confidence_threshold=min(1.0, max(0.05, detection_confidence_threshold)),
        sample_fps=min(10.0, max(0.2, detection_sample_fps)),
    )
    _set_flash(request, "detection.settings_saved")
    return _redirect(f"/cameras/{camera_id}")


@app.get("/api/cameras/{camera_id}/detections/live")
async def camera_live_detections(request: Request, camera_id: int):
    guard = _require_camera_access(request, camera_id)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    detections = database.list_detections(SETTINGS.database_path, camera_id)
    boxes: list[dict[str, Any]] = []
    for detection in detections:
        if detection.get("source") != "local_ai" or not detection.get("active"):
            continue
        raw_value = detection.get("raw_value")
        if not raw_value:
            continue
        try:
            payload = json.loads(raw_value)
        except (TypeError, ValueError):
            continue
        box = payload.get("box")
        if not isinstance(box, list) or len(box) != 4:
            continue
        boxes.append(
            {
                "key": detection["detection_key"],
                "label": detection["label"],
                "confidence": payload.get("confidence"),
                "box": box,
            }
        )
    return {"ok": True, "detections": boxes}


@app.get("/cameras/{camera_id}/detection/zones")
async def list_camera_detection_zones_route(request: Request, camera_id: int):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    zones = database.list_camera_detection_zones(SETTINGS.database_path, camera_id)
    return {"ok": True, "zones": zones}


@app.post("/cameras/{camera_id}/detection/zones")
async def create_camera_detection_zone_route(request: Request, camera_id: int):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"ok": False, "message": "Camera was not found"}, status_code=status.HTTP_404_NOT_FOUND)
    payload = await request.json()
    name = str(payload.get("name") or "").strip() or "Zone"
    mode = payload.get("mode") if payload.get("mode") in {"exclude", "loiter"} else "include"
    classes = payload.get("classes")
    classes = [key for key in classes if key in DETECTION_KEY_LABELS] if isinstance(classes, list) else None
    raw_points = payload.get("points")
    if not isinstance(raw_points, list) or len(raw_points) < 3:
        return JSONResponse({"ok": False, "message": "Eine Zone braucht mindestens drei Punkte"}, status_code=status.HTTP_400_BAD_REQUEST)
    try:
        points = [
            (max(0.0, min(1.0, float(point[0]))), max(0.0, min(1.0, float(point[1]))))
            for point in raw_points
        ]
    except (TypeError, ValueError, IndexError):
        return JSONResponse({"ok": False, "message": "Invalid point coordinates"}, status_code=status.HTTP_400_BAD_REQUEST)
    try:
        min_dwell_seconds = max(1, min(3600, int(payload.get("min_dwell_seconds") or 10)))
    except (TypeError, ValueError):
        min_dwell_seconds = 10
    zone_id = database.create_camera_detection_zone(
        SETTINGS.database_path,
        camera_id,
        name=name,
        mode=mode,
        classes=classes,
        points=points,
        min_dwell_seconds=min_dwell_seconds,
    )
    zone = database.get_camera_detection_zone(SETTINGS.database_path, zone_id)
    return {"ok": True, "zone": zone}


@app.delete("/cameras/{camera_id}/detection/zones/{zone_id}")
async def delete_camera_detection_zone_route(request: Request, camera_id: int, zone_id: int):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    database.delete_camera_detection_zone(SETTINGS.database_path, camera_id, zone_id)
    return {"ok": True}


@app.post("/cameras/{camera_id}/continuous-recording")
async def update_camera_continuous_recording(
    request: Request,
    camera_id: int,
    continuous_segment_seconds: int = Form(300),
    continuous_storage_id: str = Form(""),
    continuous_recording_enabled: str | None = Form(None),
):
    guard = _require_admin(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        _set_flash(request, "camera.not_found", None, "error")
        return _redirect("/cameras")
    try:
        camera_module = get_camera_module(camera.get("module_key"))
    except UnknownCameraModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/cameras/{camera_id}")
    if not camera_module.supports(CameraCapability.RECORDING):
        _set_flash(request, "camera.module_no_continuous_recording", {"label": camera_module.label}, "error")
        return _redirect(f"/cameras/{camera_id}")
    storage_id = int(continuous_storage_id) if continuous_storage_id else None
    database.update_camera_continuous_settings(
        SETTINGS.database_path,
        camera_id,
        continuous_recording_enabled=continuous_recording_enabled == "on",
        continuous_segment_seconds=max(60, min(1800, int(continuous_segment_seconds))),
        continuous_storage_id=storage_id,
    )
    _set_flash(request, "recording.continuous_settings_saved")
    return _redirect(f"/cameras/{camera_id}#recording")


@app.post("/cameras/{camera_id}/connection")
async def update_camera_connection(
    request: Request,
    camera_id: int,
    name: str = Form(...),
    host: str = Form(""),
    onvif_port: int = Form(8000),
    http_port: int = Form(80),
    rtsp_port: int = Form(554),
    username: str = Form(""),
    password: str = Form(""),
    manual_stream_uri: str = Form(""),
    clear_manual_stream_uri: str | None = Form(None),
):
    guard = _require_admin(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        _set_flash(request, "camera.not_found", None, "error")
        return _redirect("/cameras")
    try:
        camera_module = get_camera_module(camera.get("module_key"))
    except UnknownCameraModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/cameras/{camera_id}")
    try:
        normalized_manual_uri = (
            validate_manual_stream_uri(manual_stream_uri)
            if manual_stream_uri.strip()
            else None
        )
    except ValueError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/cameras/{camera_id}")
    clear_manual = clear_manual_stream_uri == "on"
    effective_manual_uri = normalized_manual_uri or (None if clear_manual else camera.get("manual_stream_uri"))
    if normalized_manual_uri and not camera_module.supports_manual_stream_uri:
        _set_flash(request, "camera.module_no_manual_stream", {"label": camera_module.label}, "error")
        return _redirect(f"/cameras/{camera_id}")
    if camera_module.requires_manual_stream_uri and not effective_manual_uri:
        _set_flash(request, "camera.rtsp_url_required", None, "error")
        return _redirect(f"/cameras/{camera_id}")
    normalized_host = host.strip()
    if not normalized_host and effective_manual_uri:
        normalized_host = str(urlsplit(str(effective_manual_uri)).hostname or "")
    values = {
        "name": name.strip(),
        "host": normalized_host,
        "onvif_port": max(1, min(65535, int(onvif_port))),
        "http_port": max(1, min(65535, int(http_port))),
        "rtsp_port": max(1, min(65535, int(rtsp_port))),
        "username": username.strip(),
        "password": password.strip() or None,
    }
    if not values["name"] or not values["host"] or (camera_module.requires_credentials and not values["username"]):
        _set_flash(request, "camera.name_host_credentials_required", None, "error")
        return _redirect(f"/cameras/{camera_id}")
    database.update_camera_connection(
        SETTINGS.database_path,
        camera_id,
        name=str(values["name"]),
        host=str(values["host"]),
        onvif_port=int(values["onvif_port"]),
        http_port=int(values["http_port"]),
        rtsp_port=int(values["rtsp_port"]),
        username=str(values["username"]),
        password=values["password"],
        manual_stream_uri=normalized_manual_uri,
        clear_manual_stream_uri=clear_manual,
    )
    audit.log_event(
        request,
        SETTINGS.database_path,
        "camera.credentials_updated",
        target_type="camera",
        target_id=camera_id,
        detail={"name": values["name"], "password_changed": bool(values["password"])},
    )
    SNAPSHOT_MANAGER.delete(camera_id)
    try:
        snapshot = await _refresh_camera(camera_id)
        _set_flash(request, "common.raw_message", {"message": snapshot.message})
    except Exception as exc:
        LOGGER.exception("Kamera %s konnte nach Verbindungsupdate nicht geprüft werden", camera_id)
        _set_flash(request, "connection.saved_probe_failed", {"error": exc}, "error")
    return _redirect(f"/cameras/{camera_id}")


@app.post("/cameras/{camera_id}/delete")
async def remove_camera(request: Request, camera_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_camera(SETTINGS.database_path, camera_id)
    audit.log_event(request, SETTINGS.database_path, "camera.deleted", target_type="camera", target_id=camera_id)
    SNAPSHOT_MANAGER.delete(camera_id)
    for cache_key in [key for key in CONTROL_STATE_CACHE if key[0] == camera_id]:
        CONTROL_STATE_CACHE.pop(cache_key, None)
    for cache_key in [key for key in CONTROL_STATE_PROBE_RETRY_AFTER if key[0] == camera_id]:
        CONTROL_STATE_PROBE_RETRY_AFTER.pop(cache_key, None)
    _set_flash(request, "camera.removed")
    return _redirect("/cameras")


@app.get("/storage", response_class=HTMLResponse)
async def storage_targets(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "storage.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "storage_targets": database.list_storage_targets(SETTINGS.database_path),
            "defaults": {"local_path": SETTINGS.recordings_path},
            "flash": _pop_flash(request),
        },
    )


@app.post("/storage")
async def create_storage_target(
    request: Request,
    name: str = Form(...),
    kind: str = Form("local"),
    local_path: str = Form(""),
    s3_endpoint_url: str = Form(""),
    s3_region: str = Form(""),
    s3_bucket: str = Form(""),
    s3_prefix: str = Form(""),
    s3_access_key_id: str = Form(""),
    s3_secret_access_key: str = Form(""),
):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        database.create_storage_target(
            SETTINGS.database_path,
            name=name.strip(),
            kind=_validated_storage_kind(kind),
            local_path=_none_if_blank(local_path),
            s3_endpoint_url=_none_if_blank(s3_endpoint_url),
            s3_region=_none_if_blank(s3_region),
            s3_bucket=_none_if_blank(s3_bucket),
            s3_prefix=_none_if_blank(s3_prefix),
            s3_access_key_id=_none_if_blank(s3_access_key_id),
            s3_secret_access_key=_none_if_blank(s3_secret_access_key),
        )
        audit.log_event(request, SETTINGS.database_path, "storage.created", target_type="storage", detail={"name": name.strip(), "kind": kind})
        _set_flash(request, "storage.created")
    except Exception as exc:
        _set_flash(request, "storage.create_failed", {"error": exc}, "error")
    return _redirect("/storage")


@app.post("/storage/cleanup")
async def run_cleanup(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    deleted = apply_cleanup(SETTINGS.database_path)
    _set_flash(request, "recording.clips_deleted", {"count": deleted})
    return _redirect("/storage/explorer")


@app.post("/storage/{storage_id}")
async def update_storage_target(
    request: Request,
    storage_id: int,
    name: str = Form(...),
    kind: str = Form("local"),
    local_path: str = Form(""),
    s3_endpoint_url: str = Form(""),
    s3_region: str = Form(""),
    s3_bucket: str = Form(""),
    s3_prefix: str = Form(""),
    s3_access_key_id: str = Form(""),
    s3_secret_access_key: str = Form(""),
    retention_days: str = Form(""),
    retention_max_gb: str = Form(""),
):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_storage_target(
        SETTINGS.database_path,
        storage_id,
        name=name.strip(),
        kind=_validated_storage_kind(kind),
        local_path=_none_if_blank(local_path),
        s3_endpoint_url=_none_if_blank(s3_endpoint_url),
        s3_region=_none_if_blank(s3_region),
        s3_bucket=_none_if_blank(s3_bucket),
        s3_prefix=_none_if_blank(s3_prefix),
        s3_access_key_id=_none_if_blank(s3_access_key_id),
        s3_secret_access_key=_none_if_blank(s3_secret_access_key),
        retention_days=int(retention_days) if retention_days else None,
        retention_max_gb=float(retention_max_gb) if retention_max_gb else None,
    )
    audit.log_event(request, SETTINGS.database_path, "storage.updated", target_type="storage", target_id=storage_id, detail={"name": name.strip(), "kind": kind})
    _set_flash(request, "storage.updated")
    return _redirect("/storage")


@app.post("/storage/{storage_id}/delete")
async def remove_storage_target(request: Request, storage_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_storage_target(SETTINGS.database_path, storage_id)
    _set_flash(request, "storage.removed")
    return _redirect("/storage")


RECORDINGS_PAGE_SIZE = 60


@app.get("/recordings", response_class=HTMLResponse)
async def recordings(
    request: Request,
    camera_id: int | None = Query(None),
    detection_key: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1),
):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    current_page = max(1, page)
    common_filters = {
        "camera_id": camera_id,
        "detection_key": detection_key or None,
        "date_from": date_from or None,
        "date_to": date_to or None,
        "search": search or None,
        "user_id": int(user["id"]),
        "role": str(user["role"]),
    }
    total = database.count_recordings(SETTINGS.database_path, **common_filters)
    total_pages = max(1, math.ceil(total / RECORDINGS_PAGE_SIZE))
    current_page = min(current_page, total_pages)
    rows = database.list_recordings(
        SETTINGS.database_path,
        **common_filters,
        limit=RECORDINGS_PAGE_SIZE,
        offset=(current_page - 1) * RECORDINGS_PAGE_SIZE,
    )
    cameras_for_user = database.list_cameras_for_user(SETTINGS.database_path, int(user["id"]), str(user["role"]))
    return templates.TemplateResponse(
        request,
        "recordings.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "recordings": rows,
            "cameras": cameras_for_user,
            "event_keys": database.list_recording_event_keys(SETTINGS.database_path),
            "filters": {
                "camera_id": camera_id,
                "detection_key": detection_key or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
                "search": search or "",
            },
            "total": total,
            "page": current_page,
            "total_pages": total_pages,
            "page_size": RECORDINGS_PAGE_SIZE,
            "flash": _pop_flash(request),
        },
    )


@app.get("/timeline", response_class=HTMLResponse)
async def timeline_view(
    request: Request,
    camera_id: int | None = Query(None),
    day: str | None = Query(None),
):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    cameras = database.list_cameras_for_user(SETTINGS.database_path, int(user["id"]), str(user["role"]))
    available_camera_ids = {int(camera["id"]) for camera in cameras}
    selected_camera_id = camera_id if camera_id in available_camera_ids else (int(cameras[0]["id"]) if cameras else None)
    selected_day = _parse_date(day, date.today())

    selected_camera = None
    timeline_segments: list[dict[str, Any]] = []
    timeline_events: list[dict[str, Any]] = []
    sd_card_available = False
    if selected_camera_id is not None:
        access_guard = _require_camera_access(request, selected_camera_id)
        if access_guard:
            return access_guard
        selected_camera = database.get_camera(SETTINGS.database_path, selected_camera_id)
        sd_card_available = bool(selected_camera) and _camera_supports(selected_camera, CameraCapability.ARCHIVE)
        start_at = f"{selected_day.isoformat()}T00:00:00"
        end_at = f"{(selected_day + timedelta(days=1)).isoformat()}T00:00:00"
        rows = database.list_recordings_for_range(
            SETTINGS.database_path,
            camera_id=selected_camera_id,
            start_at=start_at,
            end_at=end_at,
        )
        timeline_segments = _timeline_payload(row for row in rows if row["detection_key"] == "continuous")
        timeline_events = _timeline_payload(row for row in rows if row["detection_key"] != "continuous")

    return templates.TemplateResponse(
        request,
        "timeline.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "cameras": cameras,
            "selected_camera": selected_camera,
            "selected_camera_id": selected_camera_id,
            "selected_day": selected_day.isoformat(),
            "prev_day": (selected_day - timedelta(days=1)).isoformat(),
            "next_day": (selected_day + timedelta(days=1)).isoformat(),
            "today": date.today().isoformat(),
            "is_today": selected_day == date.today(),
            "sd_card_available": sd_card_available,
            "timeline_data": {
                "segments": timeline_segments,
                "events": timeline_events,
                "day": selected_day.isoformat(),
                "camera_id": selected_camera_id,
                "sd_card_available": sd_card_available,
            },
            "has_segments": bool(timeline_segments or timeline_events),
            "flash": _pop_flash(request),
        },
    )


@app.get("/activity", response_class=HTMLResponse)
async def activity_view(request: Request, day: str | None = Query(None)):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    cameras = database.list_cameras_for_user(SETTINGS.database_path, int(user["id"]), str(user["role"]))
    selected_day = _parse_date(day, date.today())
    start_at = f"{selected_day.isoformat()}T00:00:00"
    end_at = f"{(selected_day + timedelta(days=1)).isoformat()}T00:00:00"

    camera_ids = [int(camera["id"]) for camera in cameras]
    rows = database.list_event_recordings_for_cameras_range(
        SETTINGS.database_path,
        camera_ids=camera_ids,
        start_at=start_at,
        end_at=end_at,
    )
    events_by_camera: dict[int, list[dict[str, Any]]] = {camera_id: [] for camera_id in camera_ids}
    for row in rows:
        events_by_camera.setdefault(int(row["camera_id"]), []).append(row)

    activity_cameras = [
        {
            "id": int(camera["id"]),
            "name": camera["name"],
            "events": _timeline_payload(events_by_camera.get(int(camera["id"]), [])),
            "sd_card_available": _camera_supports(camera, CameraCapability.ARCHIVE),
        }
        for camera in cameras
    ]
    total_events = sum(len(camera["events"]) for camera in activity_cameras)
    any_sd_card_available = any(camera["sd_card_available"] for camera in activity_cameras)

    return templates.TemplateResponse(
        request,
        "activity.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "selected_day": selected_day.isoformat(),
            "prev_day": (selected_day - timedelta(days=1)).isoformat(),
            "next_day": (selected_day + timedelta(days=1)).isoformat(),
            "today": date.today().isoformat(),
            "is_today": selected_day == date.today(),
            "activity_cameras": activity_cameras,
            "total_events": total_events,
            "any_sd_card_available": any_sd_card_available,
            "activity_data": {
                "day": selected_day.isoformat(),
                "cameras": activity_cameras,
            },
            "flash": _pop_flash(request),
        },
    )


@app.get("/sd-card", response_class=HTMLResponse)
async def sd_card(
    request: Request,
    camera_id: int | None = Query(None),
    channel: int | None = Query(None),
    stream: str = Query("main"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    cameras = [
        camera
        for camera in database.list_cameras_for_user(SETTINGS.database_path, int(user["id"]), str(user["role"]))
        if _camera_supports(camera, CameraCapability.ARCHIVE)
    ]
    available_camera_ids = {int(camera["id"]) for camera in cameras}
    selected_camera_id = camera_id if camera_id in available_camera_ids else (int(cameras[0]["id"]) if cameras else None)
    selected_camera = None
    channels: list[dict[str, Any]] = []
    error_key: str | None = None
    today = date.today()
    start_date = _parse_date(date_from, today)
    end_date = _parse_date(date_to, start_date)
    stream_value = "sub" if stream == "sub" else "main"
    selected_channel = channel or 0

    if selected_camera_id is None:
        error_key = "sd_card.no_archive_camera"
    else:
        access_guard = _require_camera_access(request, selected_camera_id)
        if access_guard:
            return access_guard
        selected_camera = database.get_camera(SETTINGS.database_path, selected_camera_id)
        if selected_camera is None:
            error_key = "camera.not_found"
        else:
            channels = database.list_camera_channels(SETTINGS.database_path, selected_camera_id)
            if not channels:
                channels = [
                    {
                        "id": None,
                        "channel_index": 0,
                        "name": selected_camera["name"],
                        "enabled": 1,
                    }
                ]
            known_channel_indices = {int(item["channel_index"]) for item in channels}
            selected_channel = channel if channel in known_channel_indices else int(channels[0]["channel_index"])
            if start_date > end_date:
                error_key = "sd_card.start_after_end"
    return templates.TemplateResponse(
        request,
        "sd_card.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "cameras": cameras,
            "selected_camera": selected_camera,
            "channels": channels,
            "error": _t_en(error_key) if error_key else None,
            "error_key": error_key,
            "filters": {
                "camera_id": selected_camera_id,
                "channel": selected_channel,
                "stream": stream_value,
                "date_from": start_date.isoformat(),
                "date_to": end_date.isoformat(),
            },
            "flash": _pop_flash(request),
        },
    )


@app.get("/api/sd-card/recordings")
async def sd_card_recordings_api(
    request: Request,
    camera_id: int = Query(...),
    channel: int | None = Query(None),
    stream: str = Query("main"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    if not _is_logged_in(request):
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    user = _current_user(request)
    if not database.user_can_access_camera(SETTINGS.database_path, int(user["id"]), str(user["role"]), camera_id):
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    selected_camera = database.get_camera(SETTINGS.database_path, camera_id)
    if selected_camera is None:
        return JSONResponse({"error": "Camera was not found"}, status_code=status.HTTP_404_NOT_FOUND)
    try:
        camera_module = get_camera_module(selected_camera.get("module_key"))
    except UnknownCameraModuleError as exc:
        return JSONResponse({"error": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)
    if not camera_module.supports(CameraCapability.ARCHIVE):
        return JSONResponse(
            {"error": f"The {camera_module.label} module does not support a camera archive"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    today = date.today()
    start_date = _parse_date(date_from, today)
    end_date = _parse_date(date_to, start_date)
    if start_date > end_date:
        return JSONResponse({"error": "The start date must not be after the end date"}, status_code=status.HTTP_400_BAD_REQUEST)

    channels = database.list_camera_channels(SETTINGS.database_path, camera_id)
    if not channels:
        channels = [{"channel_index": 0}]
    known_channel_indices = {int(item["channel_index"]) for item in channels}
    selected_channel = channel if channel in known_channel_indices else int(channels[0]["channel_index"])
    stream_value = "sub" if stream == "sub" else "main"

    try:
        recordings = await camera_module.list_archive_recordings(
            selected_camera,
            channel=selected_channel,
            start=datetime.combine(start_date, time.min),
            end=datetime.combine(end_date, time.max.replace(microsecond=0)),
            stream=stream_value,
        )
    except Exception as exc:
        return JSONResponse(
            {"error": f"SD-Card-Inhalte konnten nicht gelesen werden: {exc}"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    return {
        "recordings": [_sd_card_recording_payload(camera_id, row) for row in recordings],
        "filters": {
            "camera_id": camera_id,
            "channel": selected_channel,
            "stream": stream_value,
            "date_from": start_date.isoformat(),
            "date_to": end_date.isoformat(),
        },
    }


@app.get("/sd-card/{camera_id}/media")
async def sd_card_media(
    request: Request,
    camera_id: int,
    channel: int = Query(0),
    source: str = Query(...),
    start: str = Query(""),
    end: str = Query(""),
    stream: str = Query("main"),
    download: bool = Query(False),
    embed: bool = Query(False),
):
    guard = _require_camera_access(request, camera_id)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    try:
        camera_module = get_camera_module(camera.get("module_key"))
    except UnknownCameraModuleError as exc:
        return JSONResponse({"error": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)
    if not camera_module.supports(CameraCapability.ARCHIVE):
        return JSONResponse(
            {"error": f"The {camera_module.label} module does not support a camera archive"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        download_stream = await camera_module.open_archive_download(
            camera,
            channel=channel,
            source=source,
            start_id=start,
            end_id=end,
            stream=stream,
        )
    except Exception as exc:
        if embed:
            return JSONResponse({"error": str(exc)}, status_code=status.HTTP_502_BAD_GATEWAY)
        _set_flash(request, "sd_card.open_failed", {"error": exc}, "error")
        return _redirect(f"/sd-card?camera_id={camera_id}&channel={channel}&stream={stream}")
    disposition = "attachment" if download else "inline"
    headers = {
        "Content-Length": str(download_stream.length),
        "Content-Disposition": f'{disposition}; filename="{_safe_header_filename(download_stream.filename)}"',
    }
    return StreamingResponse(download_stream.chunks(), media_type="video/mp4", headers=headers)


@app.get("/recordings/{recording_id}/media")
async def recording_media(request: Request, recording_id: int):
    recording = _authorized_recording(request, recording_id)
    if not recording:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    local_path = recording.get("local_path")
    if local_path and Path(local_path).exists():
        return FileResponse(local_path, media_type="video/mp4", filename=recording.get("file_name") or "clip.mp4")
    url = presigned_url(recording)
    if url:
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    return JSONResponse({"error": "media not available"}, status_code=status.HTTP_404_NOT_FOUND)


@app.get("/recordings/{recording_id}/snapshot")
async def recording_snapshot(request: Request, recording_id: int):
    recording = _authorized_recording(request, recording_id)
    if not recording:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    snapshot_path = recording.get("snapshot_path")
    if snapshot_path and Path(snapshot_path).exists():
        return FileResponse(snapshot_path, media_type="image/jpeg")
    url = presigned_url(recording, snapshot=True)
    if url:
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    return JSONResponse({"error": "snapshot not available"}, status_code=status.HTTP_404_NOT_FOUND)


@app.get("/recordings/{recording_id}/download")
async def recording_download(request: Request, recording_id: int):
    recording = _authorized_recording(request, recording_id)
    if not recording:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    local_path = recording.get("local_path")
    if local_path and Path(local_path).exists():
        return FileResponse(local_path, media_type="application/octet-stream", filename=recording.get("file_name") or "clip.mp4")
    url = presigned_url(recording)
    if url:
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    return JSONResponse({"error": "download not available"}, status_code=status.HTTP_404_NOT_FOUND)


@app.post("/recordings/{recording_id}/delete")
async def recording_delete(request: Request, recording_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    recording = database.get_recording(SETTINGS.database_path, recording_id)
    if recording:
        if recording.get("locked"):
            _set_flash(request, "recording.locked_cannot_delete", None, "error")
            return _redirect("/recordings")
        delete_recording_files(recording)
        database.delete_recording_metadata(SETTINGS.database_path, recording_id)
        audit.log_event(request, SETTINGS.database_path, "recording.deleted", target_type="recording", target_id=recording_id)
        _set_flash(request, "recording.clip_deleted")
    return _redirect("/recordings")


@app.post("/recordings/{recording_id}/lock")
async def recording_lock(request: Request, recording_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    recording = database.get_recording(SETTINGS.database_path, recording_id)
    if recording:
        database.set_recording_locked(SETTINGS.database_path, recording_id, True)
        audit.log_event(request, SETTINGS.database_path, "recording.locked", target_type="recording", target_id=recording_id)
        _set_flash(request, "recording.locked")
    return _redirect("/recordings")


@app.post("/recordings/{recording_id}/unlock")
async def recording_unlock(request: Request, recording_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    recording = database.get_recording(SETTINGS.database_path, recording_id)
    if recording:
        database.set_recording_locked(SETTINGS.database_path, recording_id, False)
        audit.log_event(request, SETTINGS.database_path, "recording.unlocked", target_type="recording", target_id=recording_id)
        _set_flash(request, "recording.unlocked")
    return _redirect("/recordings")


@app.get("/users", response_class=HTMLResponse)
async def users(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "users": database.list_users(SETTINGS.database_path),
            "cameras": database.list_cameras(SETTINGS.database_path),
            "access_by_user": {
                user["id"]: database.list_user_camera_ids(SETTINGS.database_path, int(user["id"]))
                for user in database.list_users(SETTINGS.database_path)
            },
            "flash": _pop_flash(request),
        },
    )


@app.post("/users")
async def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("viewer"),
    camera_ids: list[int] = Form([]),
):
    guard = _require_admin(request)
    if guard:
        return guard
    user_id = database.create_user(
        SETTINGS.database_path,
        username=username.strip(),
        password=password,
        role=role,
    )
    database.set_user_camera_access(SETTINGS.database_path, user_id, camera_ids)
    audit.log_event(request, SETTINGS.database_path, "user.created", target_type="user", target_id=user_id, detail={"username": username.strip(), "role": role})
    _set_flash(request, "user.created")
    return _redirect("/users")


@app.post("/users/{user_id}")
async def update_user(
    request: Request,
    user_id: int,
    username: str = Form(...),
    role: str = Form("viewer"),
    password: str = Form(""),
    camera_ids: list[int] = Form([]),
):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_user(
        SETTINGS.database_path,
        user_id,
        username=username.strip(),
        role=role,
        password=password.strip() or None,
    )
    database.set_user_camera_access(SETTINGS.database_path, user_id, camera_ids)
    if request.session.get("user_id") == user_id:
        request.session["username"] = username.strip()
        request.session["role"] = "viewer" if role == "viewer" else "admin"
    audit.log_event(request, SETTINGS.database_path, "user.updated", target_type="user", target_id=user_id, detail={"username": username.strip(), "role": role, "password_changed": bool(password.strip())})
    _set_flash(request, "user.updated")
    return _redirect("/users")


@app.post("/users/{user_id}/delete")
async def remove_user(request: Request, user_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    if request.session.get("user_id") == user_id:
        _set_flash(request, "user.cannot_delete_self", None, "error")
        return _redirect("/users")
    database.delete_user(SETTINGS.database_path, user_id)
    audit.log_event(request, SETTINGS.database_path, "user.deleted", target_type="user", target_id=user_id)
    _set_flash(request, "user.deleted")
    return _redirect("/users")


@app.get("/mqtt", response_class=HTMLResponse)
async def mqtt_settings(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "mqtt.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "config": database.get_mqtt_config(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )


@app.post("/mqtt")
async def update_mqtt_settings(
    request: Request,
    host: str = Form(""),
    port: int = Form(1883),
    username: str = Form(""),
    password: str = Form(""),
    topic_prefix: str = Form("tbc"),
    discovery_prefix: str = Form("homeassistant"),
    enabled: str | None = Form(None),
    discovery_enabled: str | None = Form(None),
):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_mqtt_config(
        SETTINGS.database_path,
        enabled=enabled == "on",
        host=_none_if_blank(host),
        port=max(1, min(65535, int(port))),
        username=_none_if_blank(username),
        password=_none_if_blank(password),
        topic_prefix=topic_prefix.strip() or "tbc",
        discovery_enabled=discovery_enabled == "on",
        discovery_prefix=discovery_prefix.strip() or "homeassistant",
    )
    audit.log_event(request, SETTINGS.database_path, "mqtt.settings_updated", detail={"enabled": enabled == "on"})
    _set_flash(request, "mqtt.settings_saved")
    return _redirect("/mqtt")


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
    # Local AI detections are TBC's own inference over the raw stream, not a vendor
    # capability - recording for them uses plain ffmpeg against camera["stream_uri"]
    # and works regardless of what the assigned camera module declares.
    is_local_ai_source = any(detection.get("source") == "local_ai" for detection in detections)
    camera_module = camera_module or get_camera_module(camera.get("module_key"))
    if is_local_ai_source or camera_module.supports(CameraCapability.RECORDING):
        RECORDING_MANAGER.maybe_start_event_recordings(camera, detections)


@app.post("/cameras/{camera_id}/channels/{channel_id}")
async def update_channel(request: Request, camera_id: int, channel_id: int, name: str = Form(...), enabled: str | None = Form(None)):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_camera_channel(SETTINGS.database_path, channel_id, name=name.strip(), enabled=enabled == "on")
    _set_flash(request, "camera.channel_updated")
    return _redirect(f"/cameras/{camera_id}")


@app.get("/live", response_class=HTMLResponse)
async def live_view(request: Request):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    live_items = _live_items_for_user(user)
    return templates.TemplateResponse(
        request,
        "live.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "live_items": [_live_item_payload(item) for item in live_items],
            "wall_settings": database.get_live_wall_settings(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )


@app.post("/live/layout")
async def update_live_wall_settings(
    request: Request,
    columns: int = Form(3),
    rotation_enabled: str | None = Form(None),
    rotation_seconds: int = Form(15),
    webrtc_enabled: str | None = Form(None),
):
    guard = _require_admin(request)
    if guard:
        return guard
    webrtc_now_enabled = webrtc_enabled == "on"
    if webrtc_now_enabled:
        try:
            await asyncio.to_thread(GO2RTC_MANAGER.start)
        except RuntimeError as exc:
            # Don't persist the checkbox as "on" when go2rtc actually failed
            # to start - otherwise the setting looks enabled on reload even
            # though WebRTC never came up.
            webrtc_now_enabled = False
            _set_flash(request, "live.webrtc_start_failed", {"error": str(exc)}, "error")
    else:
        await asyncio.to_thread(GO2RTC_MANAGER.stop)
    database.set_live_wall_settings(
        SETTINGS.database_path,
        columns=columns,
        rotation_enabled=rotation_enabled == "on",
        rotation_seconds=rotation_seconds,
        webrtc_enabled=webrtc_now_enabled,
    )
    return _redirect("/live")


@app.post("/api/live/layout/item")
async def update_live_layout_item(request: Request):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    user = _current_user(request)
    payload = await request.json()
    live_key = str(payload.get("live_key") or "")
    if not _live_item_for_key(user, live_key):
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    try:
        column_span = int(payload.get("column_span", 1))
        row_span = int(payload.get("row_span", 1))
        sort_order = int(payload.get("sort_order", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid payload"}, status_code=status.HTTP_400_BAD_REQUEST)
    database.set_live_layout_item(
        SETTINGS.database_path, live_key, column_span=column_span, row_span=row_span, sort_order=sort_order
    )
    return {"ok": True}


@app.get("/api/live/status")
async def live_status_api(request: Request):
    if not _is_logged_in(request):
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    user = _current_user(request)
    return {"items": [_live_item_payload(item) for item in _live_items_for_user(user)]}


@app.post("/api/live/start-all")
async def start_all_live_api(request: Request):
    if not _is_logged_in(request):
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    user = _current_user(request)
    items = _live_items_for_user(user)
    for item in items:
        _start_live_item(item)
    return {"items": [_live_item_payload(item) for item in items]}


@app.post("/api/live/{live_key}/start")
async def start_live_key_api(request: Request, live_key: str):
    guard = _require_live_key_access(request, live_key)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    user = _current_user(request)
    item = _live_item_for_key(user, live_key)
    if item is None:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    _start_live_item(item)
    return {"item": _live_item_payload(item)}


@app.post("/api/live/{live_key}/stop")
async def stop_live_key_api(request: Request, live_key: str):
    guard = _require_live_key_access(request, live_key)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    LIVE_MANAGER.stop(live_key)
    user = _current_user(request)
    item = _live_item_for_key(user, live_key)
    return {"item": _live_item_payload(item) if item else {"key": live_key, "status": "stopped"}}


@app.post("/live/camera/{camera_id}/start")
async def start_camera_live(request: Request, camera_id: int):
    guard = _require_camera_access(request, camera_id)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if camera and not _camera_supports(camera, CameraCapability.LIVE):
        _set_flash(request, "camera.live_not_supported", None, "error")
        return _redirect("/live")
    uri = stream_uri_for(camera) if camera else None
    if camera and not uri:
        LOGGER.info("Kein Live-Stream fuer Kamera %s bekannt, aktualisiere Kamera-Probe", camera_id)
        await _refresh_camera(camera_id)
        camera = database.get_camera(SETTINGS.database_path, camera_id)
        uri = stream_uri_for(camera) if camera else None
    if not uri:
        _set_flash(request, "live.no_stream_known", None, "error")
        return _redirect("/live")
    try:
        live_key = f"camera-{camera_id}"
        LIVE_MANAGER.start(live_key, uri)
    except Exception as exc:
        LOGGER.exception("Live-Ansicht konnte fuer Kamera %s nicht gestartet werden", camera_id)
        _set_flash(request, "live.start_failed", {"error": exc}, "error")
    return _redirect("/live")


@app.post("/live/channel/{channel_id}/start")
async def start_channel_live(request: Request, channel_id: int):
    channel = database.get_camera_channel(SETTINGS.database_path, channel_id)
    if not channel:
        return _redirect("/live")
    guard = _require_camera_access(request, int(channel["camera_id"]))
    if guard:
        return guard
    if int(channel.get("enabled") or 0) != 1:
        _set_flash(request, "camera.channel_disabled", None, "error")
        return _redirect("/live")
    camera = database.get_camera(SETTINGS.database_path, int(channel["camera_id"]))
    if camera and not _camera_supports(camera, CameraCapability.LIVE):
        _set_flash(request, "camera.live_not_supported", None, "error")
        return _redirect("/live")
    uri = stream_uri_for(camera, channel)
    if camera and not uri:
        LOGGER.info("Kein Live-Stream fuer Kanal %s bekannt, aktualisiere Kamera-Probe", channel_id)
        await _refresh_camera(int(channel["camera_id"]))
        channel = database.get_camera_channel(SETTINGS.database_path, channel_id)
        camera = database.get_camera(SETTINGS.database_path, int(channel["camera_id"])) if channel else None
        uri = stream_uri_for(camera, channel) if camera and channel else None
    if not uri:
        _set_flash(request, "camera.channel_no_stream", None, "error")
        return _redirect("/live")
    try:
        live_key = f"channel-{channel_id}"
        LIVE_MANAGER.start(live_key, uri)
    except Exception as exc:
        LOGGER.exception("Live-Ansicht konnte fuer Kanal %s nicht gestartet werden", channel_id)
        _set_flash(request, "live.start_failed", {"error": exc}, "error")
    return _redirect("/live")


@app.post("/live/{live_key}/stop")
async def stop_live(request: Request, live_key: str):
    guard = _require_login(request)
    if guard:
        return guard
    LIVE_MANAGER.stop(live_key)
    return _redirect("/live")


@app.get("/live/{live_key}/index.m3u8")
async def live_playlist(request: Request, live_key: str):
    guard = _require_live_key_access(request, live_key)
    if guard:
        return guard
    path = LIVE_MANAGER.playlist_path(live_key)
    if not path.exists():
        return JSONResponse({"error": "not ready"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-cache"})


@app.get("/live/{live_key}/{segment}")
async def live_segment(request: Request, live_key: str, segment: str):
    guard = _require_live_key_access(request, live_key)
    if guard:
        return guard
    if not segment.endswith(".ts") or segment.startswith("."):
        return JSONResponse({"error": "invalid segment"}, status_code=status.HTTP_404_NOT_FOUND)
    path = LIVE_MANAGER.segment_path(live_key, segment)
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type="video/mp2t", headers={"Cache-Control": "no-cache"})


@app.post("/live/{live_key}/webrtc/offer")
async def live_webrtc_offer(request: Request, live_key: str):
    """WHEP signaling proxy: the browser never talks to go2rtc directly (its
    API has no auth of its own for localhost callers - see go2rtc.py) - this
    route enforces the same per-camera access check as the HLS routes above,
    then forwards the SDP offer/answer exchange. Once negotiated, the actual
    media (ICE/RTP on :8555) flows directly between the browser and go2rtc,
    same as any other WebRTC connection."""
    guard = _require_live_key_access(request, live_key)
    if guard:
        return guard
    if GO2RTC_MANAGER.status() != "running":
        return JSONResponse({"error": "WebRTC is not enabled"}, status_code=status.HTTP_404_NOT_FOUND)
    user = _current_user(request)
    item = _live_item_for_key(user, live_key)
    stream_uri = item.get("stream_uri") if item else None
    if not stream_uri:
        return JSONResponse({"error": "no stream known"}, status_code=status.HTTP_404_NOT_FOUND)
    offer_sdp = (await request.body()).decode("utf-8")
    try:
        await asyncio.to_thread(GO2RTC_MANAGER.register_stream, live_key, str(stream_uri))
        answer_sdp = await asyncio.to_thread(GO2RTC_MANAGER.exchange_sdp, live_key, offer_sdp)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=status.HTTP_502_BAD_GATEWAY)
    return Response(content=answer_sdp, media_type="application/sdp")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "debug_count": len(list_debug_log_entries(limit=600)),
            "flash": _pop_flash(request),
        },
    )


@app.get("/settings/audit-log", response_class=HTMLResponse)
async def audit_log_page(request: Request, page: int = Query(1, ge=1), action: str | None = Query(None)):
    guard = _require_admin(request)
    if guard:
        return guard
    page_size = 50
    result = database.list_audit_events(
        SETTINGS.database_path,
        limit=page_size,
        offset=(page - 1) * page_size,
        action=_none_if_blank(action) if action else None,
    )
    total_pages = max(1, (result["total"] + page_size - 1) // page_size)
    return templates.TemplateResponse(
        request,
        "audit_log.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "events": result["events"],
            "total": result["total"],
            "page": page,
            "total_pages": total_pages,
            "selected_action": action or "",
            "actions": database.list_distinct_audit_actions(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )


@app.get("/settings/backup", response_class=HTMLResponse)
async def backup_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "backup.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "flash": _pop_flash(request),
        },
    )


@app.post("/settings/backup/create")
async def create_backup_route(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    archive = backup.create_backup(SETTINGS.database_path, SETTINGS.secret_key)
    audit.log_event(request, SETTINGS.database_path, "backup.created")
    filename = f"tbc-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tbcbackup"
    return Response(
        archive,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/settings/backup/restore")
async def restore_backup_route(request: Request, backup_file: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        data = await backup_file.read(500 * 1024 * 1024 + 1)
        backup.restore_backup(data, SETTINGS.database_path, SETTINGS.secret_key)
        audit.log_event(request, SETTINGS.database_path, "backup.restored")
        _set_flash(request, "backup.restore_succeeded")
    except backup.BackupError as exc:
        _set_flash(request, "backup.restore_failed", {"error": exc}, "error")
    finally:
        await backup_file.close()
    return _redirect("/settings/backup")


@app.get("/api-access", response_class=HTMLResponse)
async def api_access_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "api_access.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "api_config": database.get_api_config(SETTINGS.database_path),
            "api_tokens": database.list_api_tokens(SETTINGS.database_path),
            "mcp_endpoint_url": f"{str(request.base_url).rstrip('/')}/mcp/mcp",
            "api_examples": _api_examples(),
            "mcp_tools": _mcp_tool_examples(),
            "flash": _pop_flash(request),
        },
    )


@app.post("/settings/api")
async def update_api_settings(
    request: Request,
    enabled: str | None = Form(None),
    require_api_key: str | None = Form(None),
):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_api_config(
        SETTINGS.database_path,
        enabled=enabled == "on",
        require_api_key=require_api_key == "on",
    )
    audit.log_event(request, SETTINGS.database_path, "api.settings_updated", detail={"enabled": enabled == "on", "require_api_key": require_api_key == "on"})
    _set_flash(request, "api.settings_saved")
    return _redirect("/api-access")


@app.post("/settings/api-tokens")
async def create_api_token_route(request: Request, name: str = Form(...), can_control: str | None = Form(None)):
    guard = _require_admin(request)
    if guard:
        return guard
    user = _current_user(request)
    key = generate_api_key()
    control = can_control == "on"
    token_id = database.create_api_token(
        SETTINGS.database_path,
        name=name.strip() or "API token",
        key_hash=hash_api_key(key),
        key_prefix=key[:12],
        created_by_user_id=int(user["id"]),
        can_control=control,
    )
    audit.log_event(request, SETTINGS.database_path, "api_token.created", target_type="api_token", target_id=token_id, detail={"name": name, "can_control": control})
    _set_flash(request, "api.key_generated", {"key": key})
    return _redirect("/api-access")


@app.post("/settings/api-tokens/{token_id}/revoke")
async def revoke_api_token_route(request: Request, token_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.revoke_api_token(SETTINGS.database_path, token_id)
    audit.log_event(request, SETTINGS.database_path, "api_token.revoked", target_type="api_token", target_id=token_id)
    _set_flash(request, "api.key_revoked")
    return _redirect("/api-access")


@app.get("/detection", response_class=HTMLResponse)
async def detection_overview_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    model_ready = DETECTION_MODEL_PATH.exists() and DETECTION_MODEL_PATH.stat().st_size > 0
    coral_model_ready = DETECTION_CORAL_MODEL_PATH.exists() and DETECTION_CORAL_MODEL_PATH.stat().st_size > 0
    return templates.TemplateResponse(
        request,
        "detection.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "backend_status": detection_factory.backend_status(),
            "detection_backend_labels": detection_factory.BACKEND_LABELS,
            "model_ready": model_ready,
            "model_size_mb": round(DETECTION_MODEL_PATH.stat().st_size / (1024 * 1024), 1) if model_ready else None,
            "model_path": str(DETECTION_MODEL_PATH),
            "coral_model_ready": coral_model_ready,
            "coral_model_size_mb": round(DETECTION_CORAL_MODEL_PATH.stat().st_size / (1024 * 1024), 1) if coral_model_ready else None,
            "coral_model_path": str(DETECTION_CORAL_MODEL_PATH),
            "default_sample_fps": SETTINGS.detection_default_sample_fps,
            "default_confidence_threshold": SETTINGS.detection_default_confidence_threshold,
            "cameras": database.list_enabled_camera_detection_settings(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )


@app.get("/recognition", response_class=HTMLResponse)
async def recognition_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "recognition.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "settings": database.get_recognition_settings(SETTINGS.database_path),
            "known_faces": database.list_known_faces(SETTINGS.database_path),
            "known_plates": database.list_known_plates(SETTINGS.database_path),
            "recent_events": database.list_recognition_events(SETTINGS.database_path, limit=25),
            "flash": _pop_flash(request),
        },
    )


@app.post("/recognition/settings")
async def update_recognition_settings_route(
    request: Request,
    face_enabled: str | None = Form(None),
    face_mode: str = Form("snapshot"),
    face_match_threshold: str = Form("0.363"),
    plate_enabled: str | None = Form(None),
    plate_mode: str = Form("snapshot"),
):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        threshold = max(0.0, min(1.0, float(face_match_threshold or 0.363)))
    except ValueError:
        threshold = 0.363
    database.update_recognition_settings(
        SETTINGS.database_path,
        face_enabled=bool(face_enabled),
        face_mode="live" if face_mode == "live" else "snapshot",
        face_match_threshold=threshold,
        plate_enabled=bool(plate_enabled),
        plate_mode="live" if plate_mode == "live" else "snapshot",
    )
    _set_flash(request, "recognition.settings_saved")
    return _redirect("/recognition")


@app.post("/recognition/faces")
async def create_known_face_route(request: Request, name: str = Form(...), photo: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        import cv2
        import numpy as np

        raw = await photo.read(10 * 1024 * 1024 + 1)
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Image file could not be read")
        recognizer = get_face_recognizer(RECOGNITION_MODELS_DIR)
        if recognizer is None:
            raise RuntimeError("Face recognition model could not be loaded")
        faces = recognizer.detect_and_embed(image)
        if not faces:
            raise ValueError("No face found in the photo")
        face = max(faces, key=lambda item: item["score"])
        database.create_known_face(
            SETTINGS.database_path, name=name.strip(), embedding=json.dumps(face["embedding"])
        )
        _set_flash(request, "face.saved", {"name": name.strip()})
    except Exception as exc:
        _set_flash(request, "face.save_failed", {"error": exc}, "error")
    finally:
        await photo.close()
    return _redirect("/recognition")


@app.post("/recognition/faces/{face_id}/delete")
async def delete_known_face_route(request: Request, face_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_known_face(SETTINGS.database_path, face_id)
    _set_flash(request, "face.removed")
    return _redirect("/recognition")


@app.post("/recognition/plates")
async def create_known_plate_route(request: Request, plate_text: str = Form(...), label: str = Form("")):
    guard = _require_admin(request)
    if guard:
        return guard
    database.create_known_plate(SETTINGS.database_path, plate_text=plate_text, label=label.strip() or None)
    _set_flash(request, "plate.saved")
    return _redirect("/recognition")


@app.post("/recognition/plates/{plate_id}")
async def update_known_plate_route(
    request: Request, plate_id: int, plate_text: str = Form(...), label: str = Form("")
):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_known_plate(SETTINGS.database_path, plate_id, plate_text=plate_text, label=label.strip() or None)
    _set_flash(request, "plate.updated")
    return _redirect("/recognition")


@app.post("/recognition/plates/{plate_id}/delete")
async def delete_known_plate_route(request: Request, plate_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_known_plate(SETTINGS.database_path, plate_id)
    _set_flash(request, "plate.removed")
    return _redirect("/recognition")


@app.get("/camera-modules", response_class=HTMLResponse)
async def camera_modules_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    registrations = list_camera_module_registrations()
    return templates.TemplateResponse(
        request,
        "camera_modules.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "registrations": registrations,
            "camera_counts": {
                registration.module.key: database.count_cameras_by_module(
                    SETTINGS.database_path,
                    registration.module.key,
                )
                for registration in registrations
            },
            "has_tests": {
                registration.module.key: _plugin_has_tests(registration.package)
                for registration in registrations
            },
            "flash": _pop_flash(request),
        },
    )


@app.post("/camera-modules/import")
async def import_camera_module(request: Request, plugin_file: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        archive = await plugin_file.read(10 * 1024 * 1024 + 1)
        package = install_plugin_archive(archive, SETTINGS.camera_modules_path)
        reload_camera_modules()
        _set_flash(request, "plugin.camera_installed", {"label": package.manifest.label})
    except (CameraPluginError, OSError) as exc:
        _set_flash(request, "plugin.camera_import_failed", {"error": exc}, "error")
    finally:
        await plugin_file.close()
    return _redirect("/camera-modules")


@app.get("/camera-modules/{module_key}/export")
async def export_camera_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_camera_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None or registration.package is None:
        return JSONResponse({"error": "Plugin cannot be exported"}, status_code=status.HTTP_404_NOT_FOUND)
    archive = export_plugin_archive(registration.package)
    filename = f"tbc-camera-plugin-{registration.module.key}-{registration.version}.zip"
    return Response(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/camera-modules/{module_key}/delete")
async def delete_camera_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    camera_count = database.count_cameras_by_module(SETTINGS.database_path, module_key)
    if camera_count:
        _set_flash(request, "plugin.camera_still_in_use", {"count": camera_count}, "error")
        return _redirect("/camera-modules")
    try:
        remove_external_plugin(module_key, SETTINGS.camera_modules_path)
        reload_camera_modules()
        _set_flash(request, "plugin.camera_removed")
    except (CameraPluginError, OSError) as exc:
        _set_flash(request, "plugin.camera_remove_failed", {"error": exc}, "error")
    return _redirect("/camera-modules")


@app.post("/camera-modules/{module_key}/run-tests")
async def run_camera_module_tests(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_camera_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None or registration.package is None:
        _set_flash(request, "plugin.no_tests_available", None, "error")
        return _redirect("/camera-modules")
    result = await run_plugin_tests(registration.package.path, "camera")
    if not result.ran:
        _set_flash(request, "common.raw_message", {"message": result.summary}, "error")
    else:
        LOGGER.info("Plugin-Tests für %s: %s\n%s", module_key, result.summary, result.output)
        _set_flash(request, "plugin.test_result", {"module_key": module_key, "summary": result.summary})
    return _redirect("/camera-modules")


@app.get("/cloud-modules", response_class=HTMLResponse)
async def cloud_modules_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    registrations = list_cloud_module_registrations()
    return templates.TemplateResponse(
        request,
        "cloud_modules.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "registrations": registrations,
            "account_counts": {
                registration.module.key: database.count_cloud_accounts_by_module(
                    SETTINGS.database_path, registration.module.key
                )
                for registration in registrations
            },
            "has_tests": {
                registration.module.key: _plugin_has_tests(registration.package)
                for registration in registrations
            },
            "flash": _pop_flash(request),
        },
    )


@app.post("/cloud-modules/import")
async def import_cloud_module(request: Request, plugin_file: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        archive = await plugin_file.read(10 * 1024 * 1024 + 1)
        package = install_cloud_plugin_archive(archive, SETTINGS.cloud_modules_path)
        reload_cloud_modules()
        _set_flash(request, "plugin.cloud_installed", {"label": package.manifest.label})
    except (CloudPluginError, OSError) as exc:
        _set_flash(request, "plugin.cloud_import_failed", {"error": exc}, "error")
    finally:
        await plugin_file.close()
    return _redirect("/cloud-modules")


@app.get("/cloud-modules/{module_key}/export")
async def export_cloud_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_cloud_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None:
        return JSONResponse({"error": "Plugin cannot be exported"}, status_code=status.HTTP_404_NOT_FOUND)
    archive = export_cloud_plugin_archive(registration.package)
    filename = f"tbc-cloud-plugin-{registration.module.key}-{registration.version}.zip"
    return Response(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/cloud-modules/{module_key}/delete")
async def delete_cloud_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    account_count = database.count_cloud_accounts_by_module(SETTINGS.database_path, module_key)
    if account_count:
        _set_flash(request, "plugin.cloud_still_in_use", {"count": account_count}, "error")
        return _redirect("/cloud-modules")
    try:
        remove_external_cloud_plugin(module_key, SETTINGS.cloud_modules_path)
        reload_cloud_modules()
        _set_flash(request, "plugin.cloud_removed")
    except (CloudPluginError, OSError) as exc:
        _set_flash(request, "plugin.cloud_remove_failed", {"error": exc}, "error")
    return _redirect("/cloud-modules")


@app.post("/cloud-modules/{module_key}/run-tests")
async def run_cloud_module_tests(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_cloud_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None:
        _set_flash(request, "plugin.no_tests_available", None, "error")
        return _redirect("/cloud-modules")
    result = await run_plugin_tests(registration.package.path, "cloud")
    if not result.ran:
        _set_flash(request, "common.raw_message", {"message": result.summary}, "error")
    else:
        LOGGER.info("Plugin-Tests für %s: %s\n%s", module_key, result.summary, result.output)
        _set_flash(request, "plugin.test_result", {"module_key": module_key, "summary": result.summary})
    return _redirect("/cloud-modules")


@app.get("/cloud-accounts", response_class=HTMLResponse)
async def cloud_accounts_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "cloud_accounts.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "cloud_modules": list_cloud_module_registrations(),
            "cloud_module_options": _cloud_module_selector_options(),
            "accounts": database.list_cloud_accounts(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )


@app.post("/cloud-accounts", response_class=HTMLResponse)
async def create_cloud_account_route(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    form = await request.form()
    module_key = str(form.get("module_key") or "")
    label = str(form.get("label") or "")
    try:
        cloud_module = get_cloud_module(module_key)
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    try:
        config = normalize_account_configuration(
            cloud_module.account_fields,
            {
                field.key: form.get(f"account_{field.key}")
                for field in cloud_module.account_fields
            },
        )
    except CloudAccountValidationError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    database.create_cloud_account(
        SETTINGS.database_path,
        module_key=cloud_module.key,
        label=label.strip() or cloud_module.label,
        config=config,
    )
    _set_flash(request, "cloud_account.added")
    return _redirect("/cloud-accounts")


@app.get("/cloud-accounts/{account_id}/edit", response_class=HTMLResponse)
async def edit_cloud_account_page(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    return templates.TemplateResponse(
        request,
        "cloud_account_edit.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "account": account,
            "cloud_module": cloud_module,
            "flash": _pop_flash(request),
        },
    )


@app.post("/cloud-accounts/{account_id}/edit")
async def update_cloud_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    form = await request.form()
    submitted: dict[str, Any] = {}
    for field in cloud_module.account_fields:
        value = form.get(f"account_{field.key}")
        if field.field_type == CloudAccountFieldType.PASSWORD and not value:
            value = account["config"].get(field.key, "")
        submitted[field.key] = value
    try:
        config = normalize_account_configuration(cloud_module.account_fields, submitted)
    except CloudAccountValidationError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/cloud-accounts/{account_id}/edit")
    label = str(form.get("label") or "").strip() or cloud_module.label
    database.update_cloud_account_configuration(
        SETTINGS.database_path,
        account_id,
        label=label,
        config=config,
    )
    _set_flash(request, "cloud_account.updated")
    return _redirect(f"/cloud-accounts#account-{account_id}")


@app.post("/cloud-accounts/{account_id}/delete")
async def delete_cloud_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_cloud_account(SETTINGS.database_path, account_id)
    _set_flash(request, "cloud_account.removed")
    return _redirect("/cloud-accounts")


@app.post("/cloud-accounts/{account_id}/test")
async def test_cloud_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    account_url = f"/cloud-accounts#account-{account_id}"
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(account_url)
    return await _perform_cloud_account_login_attempt(
        request, account_id, cloud_module, account, success_redirect=account_url
    )


@app.get("/cloud-accounts/{account_id}/verify", response_class=HTMLResponse)
async def cloud_account_verify_page(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    field_key = account.get("pending_verification_field")
    if not field_key:
        _set_flash(request, "cloud_account.no_pending_verification", None, "error")
        return _redirect("/cloud-accounts")
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    field = next((item for item in cloud_module.account_fields if item.key == field_key), None)
    return templates.TemplateResponse(
        request,
        "cloud_account_verify.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "account": account,
            "cloud_module": cloud_module,
            "field": field,
            "flash": _pop_flash(request),
        },
    )


@app.post("/cloud-accounts/{account_id}/verify")
async def submit_cloud_account_verification_route(request: Request, account_id: int, code: str = Form(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    field_key = account.get("pending_verification_field")
    if not field_key:
        _set_flash(request, "cloud_account.no_pending_verification", None, "error")
        return _redirect("/cloud-accounts")
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    if not code.strip():
        _set_flash(request, "cloud_account.enter_code", None, "error")
        return _redirect(f"/cloud-accounts/{account_id}/verify")
    config = dict(account.get("config") or {})
    config[field_key] = code.strip()
    database.update_cloud_account_configuration(
        SETTINGS.database_path, account_id, label=str(account["label"]), config=config
    )
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    return await _perform_cloud_account_login_attempt(
        request,
        account_id,
        cloud_module,
        account,
        success_redirect=f"/cloud-accounts#account-{account_id}",
    )


@app.get("/cloud-accounts/{account_id}/devices", response_class=HTMLResponse)
async def cloud_account_devices_page(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    devices: list[Any] = []
    error_key: str | None = None
    error_params: dict[str, Any] = {}
    try:
        devices = await asyncio.wait_for(cloud_module.discover_devices(account), timeout=CONTROL_TIMEOUT_SECONDS)
        _clear_transient_cloud_account_fields(account_id, cloud_module)
    except asyncio.TimeoutError:
        error_key = "cloud_account.discovery_timeout"
        error_params = {"seconds": CONTROL_TIMEOUT_SECONDS}
    except CloudVerificationRequired as exc:
        database.set_cloud_account_pending_verification(
            SETTINGS.database_path, account_id, field_key=exc.field_key, message=str(exc)
        )
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/cloud-accounts/{account_id}/verify")
    except CloudConnectionError as exc:
        _clear_transient_cloud_account_fields(account_id, cloud_module)
        error_key = "common.raw_message"
        error_params = {"message": str(exc)}
    except Exception as exc:
        LOGGER.info("Cloud device discovery failed for %s: %s", account_id, exc)
        error_key = "cloud_account.discovery_failed"
        error_params = {"error": str(exc)}
    existing_uris = {
        camera.get("manual_stream_uri")
        for camera in database.list_cameras(SETTINGS.database_path)
        if camera.get("manual_stream_uri")
    }
    return templates.TemplateResponse(
        request,
        "cloud_account_devices.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "account": account,
            "cloud_module": cloud_module,
            "devices": devices,
            "existing_uris": existing_uris,
            "error": _t_en(error_key, **error_params) if error_key else None,
            "error_key": error_key,
            "error_params": error_params,
            "flash": _pop_flash(request),
        },
    )


@app.post("/cloud-accounts/{account_id}/devices/import")
async def import_cloud_device_route(
    request: Request,
    account_id: int,
    name: str = Form(...),
    manual_stream_uri: str = Form(...),
    module_key: str = Form("rtsp_only"),
):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        normalized_uri = validate_manual_stream_uri(manual_stream_uri)
    except ValueError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/cloud-accounts/{account_id}/devices")
    try:
        camera_module = get_camera_module(module_key)
    except UnknownCameraModuleError:
        camera_module = get_camera_module("rtsp_only")
    camera_id = database.create_camera(
        SETTINGS.database_path,
        name=name.strip() or "Cloud camera",
        host="",
        onvif_port=camera_module.default_onvif_port,
        http_port=camera_module.default_http_port,
        username="",
        password="",
        module_key=camera_module.key,
        rtsp_port=camera_module.default_rtsp_port,
        manual_stream_uri=normalized_uri,
    )
    _set_flash(request, "camera.imported_from_cloud_account")
    return _redirect(f"/cameras/{camera_id}")


@app.get("/network-modules", response_class=HTMLResponse)
async def network_modules_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    registrations = list_network_module_registrations()
    return templates.TemplateResponse(
        request,
        "network_modules.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "registrations": registrations,
            "account_counts": {
                registration.module.key: database.count_network_accounts_by_module(
                    SETTINGS.database_path, registration.module.key
                )
                for registration in registrations
            },
            "has_tests": {
                registration.module.key: _plugin_has_tests(registration.package)
                for registration in registrations
            },
            "flash": _pop_flash(request),
        },
    )


@app.post("/network-modules/import")
async def import_network_module(request: Request, plugin_file: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        archive = await plugin_file.read(10 * 1024 * 1024 + 1)
        package = install_network_plugin_archive(archive, SETTINGS.network_modules_path)
        reload_network_modules()
        _set_flash(request, "plugin.network_installed", {"label": package.manifest.label})
    except (NetworkPluginError, OSError) as exc:
        _set_flash(request, "plugin.network_import_failed", {"error": exc}, "error")
    finally:
        await plugin_file.close()
    return _redirect("/network-modules")


@app.get("/network-modules/{module_key}/export")
async def export_network_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_network_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None:
        return JSONResponse({"error": "Plugin cannot be exported"}, status_code=status.HTTP_404_NOT_FOUND)
    archive = export_network_plugin_archive(registration.package)
    filename = f"tbc-network-plugin-{registration.module.key}-{registration.version}.zip"
    return Response(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/network-modules/{module_key}/delete")
async def delete_network_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    account_count = database.count_network_accounts_by_module(SETTINGS.database_path, module_key)
    if account_count:
        _set_flash(request, "plugin.network_still_in_use", {"count": account_count}, "error")
        return _redirect("/network-modules")
    try:
        remove_external_network_plugin(module_key, SETTINGS.network_modules_path)
        reload_network_modules()
        _set_flash(request, "plugin.network_removed")
    except (NetworkPluginError, OSError) as exc:
        _set_flash(request, "plugin.network_remove_failed", {"error": exc}, "error")
    return _redirect("/network-modules")


@app.post("/network-modules/{module_key}/run-tests")
async def run_network_module_tests(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_network_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None:
        _set_flash(request, "plugin.no_tests_available", None, "error")
        return _redirect("/network-modules")
    result = await run_plugin_tests(registration.package.path, "network")
    if not result.ran:
        _set_flash(request, "common.raw_message", {"message": result.summary}, "error")
    else:
        LOGGER.info("Plugin-Tests für %s: %s\n%s", module_key, result.summary, result.output)
        _set_flash(request, "plugin.test_result", {"module_key": module_key, "summary": result.summary})
    return _redirect("/network-modules")


@app.get("/network-accounts", response_class=HTMLResponse)
async def network_accounts_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "network_accounts.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "network_modules": list_network_module_registrations(),
            "network_module_options": _network_module_selector_options(),
            "accounts": database.list_network_accounts(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )


@app.post("/network-accounts", response_class=HTMLResponse)
async def create_network_account_route(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    form = await request.form()
    module_key = str(form.get("module_key") or "")
    label = str(form.get("label") or "")
    try:
        network_module = get_network_module(module_key)
    except UnknownNetworkModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/network-accounts")
    try:
        config = normalize_network_account_configuration(
            network_module.account_fields,
            {
                field.key: form.get(f"account_{field.key}")
                for field in network_module.account_fields
            },
        )
    except NetworkAccountValidationError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/network-accounts")
    database.create_network_account(
        SETTINGS.database_path,
        module_key=network_module.key,
        label=label.strip() or network_module.label,
        config=config,
    )
    _set_flash(request, "network_account.added")
    return _redirect("/network-accounts")


@app.get("/network-accounts/{account_id}/edit", response_class=HTMLResponse)
async def edit_network_account_page(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_network_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "network_account.not_found", None, "error")
        return _redirect("/network-accounts")
    try:
        network_module = get_network_module(account["module_key"])
    except UnknownNetworkModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/network-accounts")
    return templates.TemplateResponse(
        request,
        "network_account_edit.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "account": account,
            "network_module": network_module,
            "flash": _pop_flash(request),
        },
    )


@app.post("/network-accounts/{account_id}/edit")
async def update_network_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_network_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "network_account.not_found", None, "error")
        return _redirect("/network-accounts")
    try:
        network_module = get_network_module(account["module_key"])
    except UnknownNetworkModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/network-accounts")
    form = await request.form()
    submitted: dict[str, Any] = {}
    for field in network_module.account_fields:
        value = form.get(f"account_{field.key}")
        if field.field_type == NetworkAccountFieldType.PASSWORD and not value:
            value = account["config"].get(field.key, "")
        submitted[field.key] = value
    try:
        config = normalize_network_account_configuration(network_module.account_fields, submitted)
    except NetworkAccountValidationError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/network-accounts/{account_id}/edit")
    label = str(form.get("label") or "").strip() or network_module.label
    database.update_network_account_configuration(
        SETTINGS.database_path,
        account_id,
        label=label,
        config=config,
    )
    _set_flash(request, "network_account.updated")
    return _redirect(f"/network-accounts#account-{account_id}")


@app.post("/network-accounts/{account_id}/delete")
async def delete_network_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_network_account(SETTINGS.database_path, account_id)
    NETWORK_STATE_CACHE.pop(account_id, None)
    _set_flash(request, "network_account.removed")
    return _redirect("/network-accounts")


@app.post("/network-accounts/{account_id}/test")
async def test_network_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account_url = f"/network-accounts#account-{account_id}"
    account = database.get_network_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "network_account.not_found", None, "error")
        return _redirect(account_url)
    try:
        network_module = get_network_module(account["module_key"])
    except UnknownNetworkModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(account_url)
    try:
        devices = await asyncio.wait_for(
            network_module.discover_devices(account), timeout=CONTROL_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        message = _t_en("network_account.discovery_timeout", seconds=CONTROL_TIMEOUT_SECONDS)
        database.update_network_account_test_result(SETTINGS.database_path, account_id, status="error", message=message)
        _set_flash(request, "common.raw_message", {"message": message}, "error")
        return _redirect(account_url)
    except NetworkConnectionError as exc:
        database.update_network_account_test_result(SETTINGS.database_path, account_id, status="error", message=str(exc))
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(account_url)
    except Exception as exc:
        LOGGER.info("Network account test failed for %s: %s", account_id, exc)
        message = str(exc)
        database.update_network_account_test_result(SETTINGS.database_path, account_id, status="error", message=message)
        _set_flash(request, "common.raw_message", {"message": message}, "error")
        return _redirect(account_url)
    NETWORK_STATE_CACHE[account_id] = [_network_device_to_dict(device) for device in devices]
    message = _t_en("network_account.connected_devices_found", count=len(devices))
    database.update_network_account_test_result(SETTINGS.database_path, account_id, status="ok", message=message)
    _set_flash(request, "common.raw_message", {"message": message})
    return _redirect(account_url)


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


@app.get("/design", response_class=HTMLResponse)
async def design_themes_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    active_theme_key = database.get_active_theme_key(SETTINGS.database_path)
    return templates.TemplateResponse(
        request,
        "design.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "registrations": list_theme_registrations(),
            "active_theme_key": active_theme_key,
            "flash": _pop_flash(request),
        },
    )


@app.post("/design/activate")
async def activate_design_theme(request: Request, theme_key: str = Form(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        get_theme_registration(theme_key)
    except UnknownThemeError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/design")
    database.set_active_theme_key(SETTINGS.database_path, theme_key.strip().lower())
    _set_flash(request, "design.activated")
    return _redirect("/design")


@app.post("/design/import")
async def import_design_theme(request: Request, theme_file: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        archive = await theme_file.read(5 * 1024 * 1024 + 1)
        package = install_theme_archive(archive, SETTINGS.theme_modules_path)
        reload_themes()
        _set_flash(request, "design.installed", {"label": package.manifest.label})
    except (ThemePackageError, OSError) as exc:
        _set_flash(request, "design.import_failed", {"error": exc}, "error")
    finally:
        await theme_file.close()
    return _redirect("/design")


@app.get("/design/{theme_key}/export")
async def export_design_theme(request: Request, theme_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        registration = get_theme_registration(theme_key)
    except UnknownThemeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)
    archive = export_theme_archive(registration.package)
    filename = f"tbc-design-{registration.manifest.key}-{registration.manifest.version}.zip"
    return Response(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/design/{theme_key}/delete")
async def delete_design_theme(request: Request, theme_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    active_theme_key = database.get_active_theme_key(SETTINGS.database_path)
    if theme_key.strip().lower() == active_theme_key:
        _set_flash(request, "design.cannot_remove_active", None, "error")
        return _redirect("/design")
    try:
        remove_external_theme(theme_key, SETTINGS.theme_modules_path)
        reload_themes()
        _set_flash(request, "design.removed")
    except (ThemePackageError, OSError) as exc:
        _set_flash(request, "design.remove_failed", {"error": exc}, "error")
    return _redirect("/design")


_PLUGIN_TEMPLATE_BUILDERS = {
    "camera": (build_camera_plugin_template, "acme_camera"),
    "cloud": (build_cloud_plugin_template, "acme_cloud"),
    "network": (build_network_plugin_template, "acme_network"),
    "design": (build_design_theme_template, "acme_design"),
}


@app.get("/plugin-sources/template/{plugin_kind}")
async def download_plugin_template(request: Request, plugin_kind: str):
    guard = _require_admin(request)
    if guard:
        return guard
    entry = _PLUGIN_TEMPLATE_BUILDERS.get(plugin_kind)
    if entry is None:
        return JSONResponse({"error": "Unknown plugin type"}, status_code=status.HTTP_404_NOT_FOUND)
    builder, name = entry
    return Response(
        builder(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="tbc-plugin-vorlage-{name}.zip"'},
    )


@app.get("/plugin-sources", response_class=HTMLResponse)
async def plugin_sources_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    sources = database.list_plugin_sources(SETTINGS.database_path)
    return templates.TemplateResponse(
        request,
        "plugin_sources.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "sources": sources,
            "standard_sources": [
                {
                    "source": standard_source,
                    "registered_source": _find_registered_standard_source(standard_source, sources),
                }
                for standard_source in STANDARD_PLUGIN_SOURCES
            ],
            "flash": _pop_flash(request),
        },
    )


@app.post("/plugin-sources")
async def create_plugin_source_route(
    request: Request,
    plugin_kind: str = Form(...),
    label: str = Form(""),
    repo_url: str = Form(...),
    ref: str = Form("main"),
    subdirectory: str = Form(""),
):
    guard = _require_admin(request)
    if guard:
        return guard
    if plugin_kind not in ("camera", "cloud", "network", "design"):
        _set_flash(request, "plugin.invalid_kind", None, "error")
        return _redirect("/plugin-sources")
    try:
        parse_github_repo_url(repo_url)
    except PluginSourceError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/plugin-sources")
    database.create_plugin_source(
        SETTINGS.database_path,
        plugin_kind=plugin_kind,
        label=label.strip() or repo_url.strip(),
        repo_url=repo_url.strip(),
        ref=ref.strip() or "main",
        subdirectory=subdirectory.strip(),
    )
    _set_flash(request, "plugin_source.added")
    return _redirect("/plugin-sources")


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


@app.post("/plugin-sources/standard/{source_key}/install")
async def install_standard_plugin_source_route(request: Request, source_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    standard_source = get_standard_plugin_source(source_key)
    if standard_source is None:
        _set_flash(request, "plugin_source.standard_not_found", None, "error")
        return _redirect("/plugin-sources")
    registered_source = _find_registered_standard_source(
        standard_source, database.list_plugin_sources(SETTINGS.database_path)
    )
    if registered_source is None:
        source_id = database.create_plugin_source(
            SETTINGS.database_path,
            plugin_kind=standard_source.plugin_kind,
            label=standard_source.label,
            repo_url=standard_source.repo_url,
            ref=standard_source.ref,
            subdirectory=standard_source.subdirectory,
        )
    else:
        source_id = int(registered_source["id"])
    return await _sync_plugin_source(request, source_id, "/plugin-sources")


@app.post("/plugin-sources/{source_id}/sync")
async def sync_plugin_source_route(request: Request, source_id: int, return_to: str = Form("/plugin-sources")):
    guard = _require_admin(request)
    if guard:
        return guard
    redirect_target = return_to if return_to in ("/plugin-sources", "/updates") else "/plugin-sources"
    return await _sync_plugin_source(request, source_id, redirect_target)


@app.post("/plugin-sources/{source_id}/delete")
async def delete_plugin_source_route(request: Request, source_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_plugin_source(SETTINGS.database_path, source_id)
    _set_flash(request, "plugin_source.removed")
    return _redirect("/plugin-sources")


@app.get("/updates", response_class=HTMLResponse)
async def plugin_updates_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    pending_sources = [
        source
        for source in database.list_plugin_sources(SETTINGS.database_path)
        if source.get("update_available")
    ]
    return templates.TemplateResponse(
        request,
        "plugin_updates.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "sources": pending_sources,
            "flash": _pop_flash(request),
        },
    )


@app.get("/license", response_class=HTMLResponse)
async def license_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    categories: list[dict[str, Any]] = []
    for entry in THIRD_PARTY_LICENSES:
        category = next((c for c in categories if c["name"] == entry["category"]), None)
        if category is None:
            category = {"name": entry["category"], "tools": []}
            categories.append(category)
        category["tools"].append(entry)
    return templates.TemplateResponse(
        request,
        "license.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "categories": categories,
            "plugin_licenses": list_plugin_licenses(),
            "flash": _pop_flash(request),
        },
    )


@app.get("/api/debug-log")
async def debug_log_api(request: Request, limit: int = Query(200)):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    return {"entries": list_debug_log_entries(limit=max(1, min(600, int(limit))))}


@app.post("/settings/debug-log/clear")
async def clear_debug_log(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    clear_debug_log_entries()
    _set_flash(request, "debug.cleared")
    return _redirect("/settings")


@app.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    system_usage = await asyncio.to_thread(current_system_usage)
    return templates.TemplateResponse(
        request,
        "health.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "system_usage": system_usage,
            "items": database.list_health_status(SETTINGS.database_path),
            "events": database.list_health_events(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )


@app.post("/api/health/refresh")
async def health_refresh_api(request: Request):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    await asyncio.to_thread(run_health_checks, SETTINGS.database_path)
    system_usage = await asyncio.to_thread(current_system_usage)
    return {
        "system_usage": system_usage,
        "items": database.list_health_status(SETTINGS.database_path),
        "events": database.list_health_events(SETTINGS.database_path),
    }


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


@app.get("/api/v1/status")
async def api_v1_status(request: Request):
    guard = _require_api_key(request)
    if guard:
        return guard
    cameras = database.list_cameras(SETTINGS.database_path)
    token = getattr(request.state, "api_token", None)
    return {
        "app_name": SETTINGS.app_name,
        "app_version": __version__,
        "update_available": APP_UPDATE_STATE["update_available"],
        "latest_version": APP_UPDATE_STATE["latest_version"],
        "camera_count": len(cameras),
        "api_can_control": bool(token and token["can_control"]),
    }


@app.get("/api/v1/cameras")
async def api_v1_cameras(request: Request):
    guard = _require_api_key(request)
    if guard:
        return guard
    cameras = database.list_cameras(SETTINGS.database_path)
    return {"cameras": [_camera_public_dict(camera) for camera in cameras]}


@app.get("/api/v1/cameras/{camera_id}")
async def api_v1_camera_detail(request: Request, camera_id: int):
    guard = _require_api_key(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return _camera_public_dict(camera)


@app.get("/api/v1/cameras/{camera_id}/snapshot")
async def api_v1_camera_snapshot(request: Request, camera_id: int):
    guard = _require_api_key(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    stream_uri = stream_uri_for(camera) if camera else None
    if not stream_uri:
        return JSONResponse({"error": "snapshot not available"}, status_code=status.HTTP_404_NOT_FOUND)
    async with SNAPSHOT_SEMAPHORE:
        snapshot_path = await asyncio.to_thread(SNAPSHOT_MANAGER.refresh_if_due, camera_id, stream_uri)
    if snapshot_path is None or not snapshot_path.exists():
        return JSONResponse({"error": "snapshot not available"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(
        snapshot_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store, max-age=0"},
    )


@app.get("/api/v1/cameras/{camera_id}/detections")
async def api_v1_camera_detections(request: Request, camera_id: int):
    guard = _require_api_key(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    detections = database.list_detections(SETTINGS.database_path, camera_id)
    return {"camera_id": camera_id, "detections": detections}


@app.get("/api/v1/cameras/{camera_id}/detection-settings")
async def api_v1_camera_detection_settings(request: Request, camera_id: int):
    guard = _require_api_key(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    settings = database.get_camera_detection_settings(SETTINGS.database_path, camera_id) or {
        "camera_id": camera_id,
        "enabled": False,
        "backend": "cpu",
        "confidence_threshold": SETTINGS.detection_default_confidence_threshold,
        "sample_fps": SETTINGS.detection_default_sample_fps,
    }
    return _detection_settings_public_dict(settings, camera_id)


@app.post("/api/v1/cameras/{camera_id}/recording")
async def api_v1_update_camera_recording(request: Request, camera_id: int):
    guard = _require_api_key_control(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    trigger_keys = database.list_camera_recording_triggers(SETTINGS.database_path, camera_id)
    database.update_camera_recording_settings(
        SETTINGS.database_path,
        camera_id,
        recording_enabled=bool(payload.get("enabled", camera["recording_enabled"])),
        recording_duration_seconds=int(payload.get("duration_seconds", camera["recording_duration_seconds"])),
        recording_pre_seconds=int(payload.get("pre_seconds", camera["recording_pre_seconds"])),
        recording_post_seconds=int(payload.get("post_seconds", camera["recording_post_seconds"])),
        recording_cooldown_seconds=int(payload.get("cooldown_seconds", camera["recording_cooldown_seconds"])),
        snapshot_enabled=bool(payload.get("snapshot_enabled", camera["snapshot_enabled"])),
        recording_storage_id=payload.get("storage_id", camera["recording_storage_id"]),
        trigger_keys=payload.get("trigger_keys", trigger_keys or ["motion"]),
    )
    audit.log_event(
        request,
        SETTINGS.database_path,
        "camera.recording_toggled_via_api",
        target_type="camera",
        target_id=camera_id,
        detail=payload,
        username_override=_api_token_username(request),
    )
    updated = database.get_camera(SETTINGS.database_path, camera_id)
    return _camera_public_dict(updated)


@app.post("/api/v1/cameras/{camera_id}/continuous-recording")
async def api_v1_update_camera_continuous_recording(request: Request, camera_id: int):
    guard = _require_api_key_control(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    database.update_camera_continuous_settings(
        SETTINGS.database_path,
        camera_id,
        continuous_recording_enabled=bool(payload.get("enabled", camera["continuous_recording_enabled"])),
        continuous_segment_seconds=int(payload.get("segment_seconds", camera["continuous_segment_seconds"])),
        continuous_storage_id=payload.get("storage_id", camera["continuous_storage_id"]),
    )
    audit.log_event(
        request,
        SETTINGS.database_path,
        "camera.continuous_recording_toggled_via_api",
        target_type="camera",
        target_id=camera_id,
        detail=payload,
        username_override=_api_token_username(request),
    )
    updated = database.get_camera(SETTINGS.database_path, camera_id)
    return _camera_public_dict(updated)


@app.post("/api/v1/cameras/{camera_id}/detection")
async def api_v1_update_camera_detection(request: Request, camera_id: int):
    guard = _require_api_key_control(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    current = database.get_camera_detection_settings(SETTINGS.database_path, camera_id) or {
        "enabled": False,
        "backend": "cpu",
        "confidence_threshold": SETTINGS.detection_default_confidence_threshold,
        "sample_fps": SETTINGS.detection_default_sample_fps,
    }
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    backend = str(payload.get("backend", current["backend"]))
    if backend not in detection_factory.BACKEND_CHOICES:
        backend = "cpu"
    database.update_camera_detection_settings(
        SETTINGS.database_path,
        camera_id,
        enabled=bool(payload.get("enabled", current["enabled"])),
        backend=backend,
        confidence_threshold=min(1.0, max(0.05, float(payload.get("confidence_threshold", current["confidence_threshold"])))),
        sample_fps=min(10.0, max(0.2, float(payload.get("sample_fps", current["sample_fps"])))),
    )
    audit.log_event(
        request,
        SETTINGS.database_path,
        "camera.detection_toggled_via_api",
        target_type="camera",
        target_id=camera_id,
        detail=payload,
        username_override=_api_token_username(request),
    )
    updated = database.get_camera_detection_settings(SETTINGS.database_path, camera_id)
    return _detection_settings_public_dict(updated, camera_id)


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


@app.get("/api/v1/cameras/{camera_id}/stream/index.m3u8")
async def api_v1_camera_stream_playlist(request: Request, camera_id: int):
    guard = _require_api_key_stream(request)
    if guard:
        return guard
    camera, uri = await _resolve_api_stream_uri(camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    if not uri:
        return JSONResponse({"error": "no live stream available for this camera"}, status_code=status.HTTP_404_NOT_FOUND)
    live_key = _api_stream_key(camera_id)
    try:
        LIVE_MANAGER.start(live_key, uri)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    # ffmpeg needs a couple of seconds to produce the first segment - wait
    # for it here instead of 404-ing immediately, since the caller here is a
    # server-side prober (Home Assistant's stream integration) rather than a
    # browser HLS player that retries the manifest on its own.
    ready, _message = await asyncio.to_thread(LIVE_MANAGER.wait_until_ready, live_key, 8)
    if not ready:
        return JSONResponse({"error": "not ready"}, status_code=status.HTTP_404_NOT_FOUND)
    path = LIVE_MANAGER.playlist_path(live_key)
    playlist_text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    rewritten = _rewrite_playlist_with_auth(
        playlist_text,
        base_url=str(request.base_url).rstrip("/"),
        camera_id=camera_id,
        api_key_value=getattr(request.state, "api_key_value", None),
    )
    return Response(
        rewritten, media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-cache"}
    )


@app.get("/api/v1/cameras/{camera_id}/stream/{segment}")
async def api_v1_camera_stream_segment(request: Request, camera_id: int, segment: str):
    guard = _require_api_key_stream(request)
    if guard:
        return guard
    if not segment.endswith(".ts") or segment.startswith("."):
        return JSONResponse({"error": "invalid segment"}, status_code=status.HTTP_404_NOT_FOUND)
    path = LIVE_MANAGER.segment_path(_api_stream_key(camera_id), segment)
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type="video/mp2t", headers={"Cache-Control": "no-cache"})


@app.post("/api/v1/cameras/{camera_id}/stream/stop")
async def api_v1_camera_stream_stop(request: Request, camera_id: int):
    guard = _require_api_key_stream(request)
    if guard:
        return guard
    LIVE_MANAGER.stop(_api_stream_key(camera_id))
    return {"status": "stopped"}


@app.get("/api/v1/recordings")
async def api_v1_recordings(
    request: Request,
    camera_id: int | None = Query(None),
    detection_key: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    guard = _require_api_key(request)
    if guard:
        return guard
    recordings = database.list_recordings(
        SETTINGS.database_path,
        camera_id=camera_id,
        detection_key=detection_key,
        date_from=date_from,
        date_to=date_to,
        role="admin",
        limit=limit,
    )
    return {"recordings": [_recording_public_dict(recording) for recording in recordings]}


@app.get("/api/v1/recordings/{recording_id}")
async def api_v1_recording_detail(request: Request, recording_id: int):
    guard = _require_api_key(request)
    if guard:
        return guard
    recording = database.get_recording(SETTINGS.database_path, recording_id)
    if not recording:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return _recording_public_dict(recording)


@app.get("/api/v1/recordings/{recording_id}/media")
async def api_v1_recording_media(request: Request, recording_id: int):
    guard = _require_api_key(request)
    if guard:
        return guard
    recording = database.get_recording(SETTINGS.database_path, recording_id)
    if not recording:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    local_path = recording.get("local_path")
    if local_path and Path(local_path).exists():
        return FileResponse(local_path, media_type="video/mp4", filename=recording.get("file_name") or "clip.mp4")
    url = presigned_url(recording)
    if url:
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    return JSONResponse({"error": "media not available"}, status_code=status.HTTP_404_NOT_FOUND)


@app.get("/api/v1/recordings/{recording_id}/snapshot")
async def api_v1_recording_snapshot(request: Request, recording_id: int):
    guard = _require_api_key(request)
    if guard:
        return guard
    recording = database.get_recording(SETTINGS.database_path, recording_id)
    if not recording:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    snapshot_path = recording.get("snapshot_path")
    if snapshot_path and Path(snapshot_path).exists():
        return FileResponse(snapshot_path, media_type="image/jpeg")
    url = presigned_url(recording, snapshot=True)
    if url:
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    return JSONResponse({"error": "snapshot not available"}, status_code=status.HTTP_404_NOT_FOUND)


@app.get("/api/v1/activity")
async def api_v1_activity(request: Request, day: str | None = Query(None)):
    guard = _require_api_key(request)
    if guard:
        return guard
    selected_day = _parse_date(day, date.today())
    cameras = database.list_cameras(SETTINGS.database_path)
    camera_ids = [int(camera["id"]) for camera in cameras]
    start_at = f"{selected_day.isoformat()}T00:00:00"
    end_at = f"{(selected_day + timedelta(days=1)).isoformat()}T00:00:00"
    rows = database.list_event_recordings_for_cameras_range(
        SETTINGS.database_path,
        camera_ids=camera_ids,
        start_at=start_at,
        end_at=end_at,
    )
    events_by_camera: dict[int, list[dict[str, Any]]] = {camera_id: [] for camera_id in camera_ids}
    for row in rows:
        events_by_camera.setdefault(int(row["camera_id"]), []).append(row)
    return {
        "day": selected_day.isoformat(),
        "cameras": [
            {
                "id": int(camera["id"]),
                "name": camera["name"],
                "events": [_recording_public_dict(row) for row in events_by_camera.get(int(camera["id"]), [])],
            }
            for camera in cameras
        ],
    }


@app.get("/api/v1/storage")
async def api_v1_storage(request: Request):
    guard = _require_api_key(request)
    if guard:
        return guard
    targets = database.list_storage_targets(SETTINGS.database_path)
    return {"storage_targets": [_storage_public_dict(target) for target in targets]}


@app.get("/api/v1/health")
async def api_v1_health(request: Request):
    guard = _require_api_key(request)
    if guard:
        return guard
    system_usage = await asyncio.to_thread(current_system_usage)
    return {
        "system_usage": system_usage,
        "items": database.list_health_status(SETTINGS.database_path),
        "events": database.list_health_events(SETTINGS.database_path),
    }


@app.get("/storage/explorer", response_class=HTMLResponse)
async def storage_explorer(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "storage_explorer.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "storage_targets": storage_overview(SETTINGS.database_path),
            "by_camera_event": database.list_recording_sizes_by_camera_event(SETTINGS.database_path),
            "cleanup_items": cleanup_preview(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )


@app.get("/retention", response_class=HTMLResponse)
async def retention_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "retention.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "rules": database.list_retention_rules(SETTINGS.database_path),
            "cameras": database.list_cameras(SETTINGS.database_path),
            "event_keys": ["continuous"]
            + sorted(
                {
                    definition.key
                    for camera_module in list_camera_modules()
                    for definition in camera_module.detection_definitions()
                }
            ),
            "flash": _pop_flash(request),
        },
    )


@app.post("/retention")
async def create_retention(request: Request, name: str = Form(...), camera_id: str = Form(""), detection_key: str = Form(""), max_age_days: str = Form(""), max_size_gb: str = Form(""), enabled: str | None = Form(None)):
    guard = _require_admin(request)
    if guard:
        return guard
    database.create_retention_rule(
        SETTINGS.database_path,
        name=name.strip(),
        enabled=enabled == "on",
        camera_id=int(camera_id) if camera_id else None,
        detection_key=_none_if_blank(detection_key),
        max_age_days=int(max_age_days) if max_age_days else None,
        max_size_gb=float(max_size_gb) if max_size_gb else None,
    )
    _set_flash(request, "retention.created")
    return _redirect("/retention")


@app.post("/retention/{rule_id}")
async def update_retention(request: Request, rule_id: int, name: str = Form(...), camera_id: str = Form(""), detection_key: str = Form(""), max_age_days: str = Form(""), max_size_gb: str = Form(""), enabled: str | None = Form(None)):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_retention_rule(
        SETTINGS.database_path,
        rule_id,
        name=name.strip(),
        enabled=enabled == "on",
        camera_id=int(camera_id) if camera_id else None,
        detection_key=_none_if_blank(detection_key),
        max_age_days=int(max_age_days) if max_age_days else None,
        max_size_gb=float(max_size_gb) if max_size_gb else None,
    )
    _set_flash(request, "retention.updated")
    return _redirect("/retention")


@app.post("/retention/{rule_id}/delete")
async def delete_retention(request: Request, rule_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_retention_rule(SETTINGS.database_path, rule_id)
    _set_flash(request, "retention.deleted")
    return _redirect("/retention")


@app.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "notifications.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "channels": database.list_notification_channels(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )


@app.post("/notifications")
async def create_notification(request: Request, name: str = Form(...), kind: str = Form("webhook"), enabled: str | None = Form(None), include_snapshot: str | None = Form(None), event_filter: str = Form(""), url: str = Form(""), token: str = Form(""), chat_id: str = Form(""), email_to: str = Form(""), email_from: str = Form(""), smtp_host: str = Form(""), smtp_port: str = Form(""), smtp_username: str = Form(""), smtp_password: str = Form(""), ha_service: str = Form("")):
    guard = _require_admin(request)
    if guard:
        return guard
    database.create_notification_channel(SETTINGS.database_path, **_notification_form_values(name, kind, enabled, include_snapshot, event_filter, url, token, chat_id, email_to, email_from, smtp_host, smtp_port, smtp_username, smtp_password, ha_service))
    _set_flash(request, "notification.created")
    return _redirect("/notifications")


@app.post("/notifications/{channel_id}")
async def update_notification(request: Request, channel_id: int, name: str = Form(...), kind: str = Form("webhook"), enabled: str | None = Form(None), include_snapshot: str | None = Form(None), event_filter: str = Form(""), url: str = Form(""), token: str = Form(""), chat_id: str = Form(""), email_to: str = Form(""), email_from: str = Form(""), smtp_host: str = Form(""), smtp_port: str = Form(""), smtp_username: str = Form(""), smtp_password: str = Form(""), ha_service: str = Form("")):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_notification_channel(SETTINGS.database_path, channel_id, **_notification_form_values(name, kind, enabled, include_snapshot, event_filter, url, token, chat_id, email_to, email_from, smtp_host, smtp_port, smtp_username, smtp_password, ha_service))
    _set_flash(request, "notification.updated")
    return _redirect("/notifications")


@app.post("/notifications/{channel_id}/delete")
async def delete_notification(request: Request, channel_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_notification_channel(SETTINGS.database_path, channel_id)
    _set_flash(request, "notification.deleted")
    return _redirect("/notifications")


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


def _is_logged_in(request: Request) -> bool:
    return bool(request.session.get("user_id"))


def _current_user(request: Request) -> dict[str, Any]:
    user_id = request.session.get("user_id")
    if not user_id:
        raise ValueError("not logged in")
    user = database.get_user(SETTINGS.database_path, int(user_id))
    if user is None:
        request.session.clear()
        raise ValueError("session user does not exist")
    request.session["username"] = user["username"]
    request.session["role"] = user["role"]
    return user


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


def _timeline_payload(rows: Any) -> list[dict[str, Any]]:
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
                "media_url": f"/recordings/{row['id']}/media",
                "snapshot_url": f"/recordings/{row['id']}/snapshot" if has_snapshot else None,
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


def _live_item_payload(item: dict[str, Any]) -> dict[str, Any]:
    live_key = str(item["key"])
    has_stream = bool(item.get("stream_uri"))
    live_status = LIVE_MANAGER.status(live_key) if has_stream else "missing"
    message = LIVE_MANAGER.message(live_key)
    if live_status == "running" and message.startswith("Starting live stream"):
        message = ""
    if not has_stream and not message:
        message = "No stream is known for live view"
    return {
        "key": live_key,
        "name": item["name"],
        "subtitle": item["subtitle"],
        "kind": item["kind"],
        "status": live_status,
        "message": message,
        "playlist_url": f"/live/{live_key}/index.m3u8",
        "webrtc_available": has_stream and GO2RTC_MANAGER.status() == "running",
        "webrtc_offer_url": f"/live/{live_key}/webrtc/offer",
        "camera_id": item.get("camera_id"),
        "control_channel": item.get("control_channel", 0),
        "ptz_supported": bool(item.get("ptz_supported")),
        "column_span": int(item.get("column_span", 1)),
        "row_span": int(item.get("row_span", 1)),
        "sort_order": int(item.get("sort_order", 0)),
    }


def _sd_card_recording_payload(camera_id: int, row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    query = {
        "channel": row.get("channel", 0),
        "stream": row.get("stream") or "main",
        "source": row.get("source") or "",
        "start": row.get("start_id") or "",
        "end": row.get("end_id") or "",
    }
    payload["media_url"] = f"/sd-card/{camera_id}/media?{urlencode({**query, 'embed': 1})}"
    payload["download_url"] = f"/sd-card/{camera_id}/media?{urlencode({**query, 'download': 1})}"
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
        "kind": kind if kind in {"telegram", "email", "webhook", "pushover", "home_assistant"} else "webhook",
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
