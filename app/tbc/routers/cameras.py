"""Camera CRUD, control, firmware, detection zones, and network mapping.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

from fastapi import Form, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import audit, database, discovery
from ..camera_modules import (
    CameraCapability,
    get_camera_module,
    list_camera_module_registrations,
)
from ..camera_modules.registry import UnknownCameraModuleError
from ..camera_modules.streams import validate_manual_stream_uri
from ..network_modules import (
    NetworkConnectionError,
    get_network_module,
)
from ..network_modules.registry import UnknownNetworkModuleError
from ..detection import factory as detection_factory
from ..detection.classes import DETECTION_KEY_LABELS
from ..live import stream_uri_for
from fastapi import APIRouter

from ..main import (
    CONTROL_STATE_CACHE,
    CONTROL_STATE_PROBE_RETRY_AFTER,
    CONTROL_TIMEOUT_SECONDS,
    FIRMWARE_UPDATE_STATE,
    LOCAL_AI_TRIGGER_DEFINITIONS,
    LOGGER,
    NETWORK_STATE_CACHE,
    SETTINGS,
    SNAPSHOT_MANAGER,
    SNAPSHOT_SEMAPHORE,
    _camera_form_error,
    _camera_module_selector_options,
    _current_user,
    _execute_control,
    _firmware_camera_and_module,
    _kick_off_control_probe,
    _kick_off_network_probe,
    _network_device_to_dict,
    _pop_flash,
    _redirect,
    _refresh_camera,
    _require_admin,
    _require_camera_access,
    _require_login,
    _run_firmware_update_task,
    _set_flash,
    _t_en,
    templates,
)

router = APIRouter()


@router.get("/cameras", response_class=HTMLResponse)
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

@router.get("/cameras/new", response_class=HTMLResponse)
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

@router.get("/cameras/discover")
async def discover_cameras(request: Request):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    try:
        cameras = await asyncio.to_thread(discovery.discover_onvif_cameras)
    except OSError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=status.HTTP_502_BAD_GATEWAY)
    return {
        "ok": True,
        "devices": [
            {
                "host": camera.host,
                "onvif_port": camera.onvif_port,
                "name": camera.name,
                "hardware": camera.hardware,
            }
            for camera in cameras
        ],
    }

@router.get("/cameras/new/local", response_class=HTMLResponse)
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

@router.post("/cameras", response_class=HTMLResponse)
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

@router.get("/cameras/{camera_id}", response_class=HTMLResponse)
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
    audio_detection_settings = database.get_camera_audio_detection_settings(SETTINGS.database_path, camera_id)
    camera_quota_rule = database.get_camera_quota_rule(SETTINGS.database_path, camera_id)
    camera_usage_gb = round(database.camera_recording_usage_bytes(SETTINGS.database_path, camera_id) / 1024**3, 2)
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
            "audio_detection_settings": audio_detection_settings,
            "camera_quota_rule": camera_quota_rule,
            "camera_usage_gb": camera_usage_gb,
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

@router.post("/cameras/{camera_id}/network")
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

@router.post("/cameras/{camera_id}/network/unlink")
async def clear_camera_network_mapping_route(request: Request, camera_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.clear_camera_network_mapping(SETTINGS.database_path, camera_id)
    _set_flash(request, "network_account.camera_unmapped")
    return _redirect(f"/cameras/{camera_id}#network")

@router.get("/cameras/{camera_id}/snapshot.jpg")
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

@router.post("/cameras/{camera_id}/refresh")
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

@router.post("/cameras/{camera_id}/control/ptz")
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

@router.post("/cameras/{camera_id}/control/floodlight")
async def control_camera_floodlight(
    request: Request, camera_id: int, state: str | None = Form(None), channel: int = Form(0)
):
    return await _execute_control(
        request, camera_id, action="floodlight", params={"state": state == "on"}, channel=channel
    )

@router.post("/cameras/{camera_id}/control/pir")
async def control_camera_pir(
    request: Request, camera_id: int, enable: str | None = Form(None), channel: int = Form(0)
):
    return await _execute_control(
        request, camera_id, action="pir", params={"enable": enable == "on"}, channel=channel
    )

@router.post("/cameras/{camera_id}/control/siren")
async def control_camera_siren(request: Request, camera_id: int, duration: int = Form(5), channel: int = Form(0)):
    return await _execute_control(
        request, camera_id, action="siren", params={"duration": duration}, channel=channel
    )

@router.post("/cameras/{camera_id}/control/reboot")
async def control_camera_reboot(request: Request, camera_id: int, channel: int = Form(0)):
    return await _execute_control(request, camera_id, action="reboot", params={}, channel=channel)

@router.post("/cameras/{camera_id}/control/zoom")
async def control_camera_zoom(request: Request, camera_id: int, position: int = Form(...), channel: int = Form(0)):
    return await _execute_control(request, camera_id, action="zoom", params={"position": position}, channel=channel)

@router.post("/cameras/{camera_id}/control/focus")
async def control_camera_focus(request: Request, camera_id: int, position: int = Form(...), channel: int = Form(0)):
    return await _execute_control(request, camera_id, action="focus", params={"position": position}, channel=channel)

@router.post("/cameras/{camera_id}/control/quick-reply")
async def control_camera_quick_reply(request: Request, camera_id: int, file_id: int = Form(...), channel: int = Form(0)):
    return await _execute_control(
        request, camera_id, action="quick_reply", params={"file_id": file_id}, channel=channel
    )

@router.post("/cameras/{camera_id}/firmware/check")
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

@router.post("/cameras/{camera_id}/firmware/update")
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

@router.get("/cameras/{camera_id}/firmware/status")
async def camera_firmware_status(request: Request, camera_id: int, channel: int = Query(0)):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    state = FIRMWARE_UPDATE_STATE.get((camera_id, channel), {"status": "idle", "progress": 0, "message": ""})
    return {"ok": True, **state}

@router.post("/cameras/{camera_id}/recording")
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

@router.post("/cameras/{camera_id}/storage-quota")
async def update_camera_storage_quota(
    request: Request,
    camera_id: int,
    quota_max_age_days: str = Form(""),
    quota_max_size_gb: str = Form(""),
):
    guard = _require_admin(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        _set_flash(request, "camera.not_found", None, "error")
        return _redirect("/cameras")
    try:
        max_age = max(1, int(quota_max_age_days)) if quota_max_age_days.strip() else None
        max_gb = max(0.1, float(quota_max_size_gb)) if quota_max_size_gb.strip() else None
    except ValueError:
        _set_flash(request, "common.raw_message", {"message": "Invalid quota value"}, "error")
        return _redirect(f"/cameras/{camera_id}")
    existing = database.get_camera_quota_rule(SETTINGS.database_path, camera_id)
    if max_age is None and max_gb is None:
        if existing:
            database.delete_retention_rule(SETTINGS.database_path, int(existing["id"]))
    elif existing:
        database.update_retention_rule(
            SETTINGS.database_path,
            int(existing["id"]),
            name=str(existing.get("name") or f"Quota: {camera['name']}"),
            enabled=True,
            camera_id=camera_id,
            detection_key=None,
            max_age_days=max_age,
            max_size_gb=max_gb,
        )
    else:
        database.create_retention_rule(
            SETTINGS.database_path,
            name=f"Quota: {camera['name']}",
            enabled=True,
            camera_id=camera_id,
            detection_key=None,
            max_age_days=max_age,
            max_size_gb=max_gb,
        )
    _set_flash(request, "camera.quota_saved")
    return _redirect(f"/cameras/{camera_id}")

@router.post("/cameras/{camera_id}/detection")
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

@router.post("/cameras/{camera_id}/audio-detection")
async def update_camera_audio_detection(
    request: Request,
    camera_id: int,
    audio_detection_confidence_threshold: float = Form(0.5),
    audio_detection_enabled: str | None = Form(None),
):
    guard = _require_admin(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        _set_flash(request, "camera.not_found", None, "error")
        return _redirect("/cameras")
    database.update_camera_audio_detection_settings(
        SETTINGS.database_path,
        camera_id,
        enabled=audio_detection_enabled == "on",
        confidence_threshold=min(1.0, max(0.05, audio_detection_confidence_threshold)),
    )
    _set_flash(request, "detection.settings_saved")
    return _redirect(f"/cameras/{camera_id}")

@router.get("/cameras/{camera_id}/detection/zones")
async def list_camera_detection_zones_route(request: Request, camera_id: int):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    zones = database.list_camera_detection_zones(SETTINGS.database_path, camera_id)
    return {"ok": True, "zones": zones}

@router.post("/cameras/{camera_id}/detection/zones")
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

@router.delete("/cameras/{camera_id}/detection/zones/{zone_id}")
async def delete_camera_detection_zone_route(request: Request, camera_id: int, zone_id: int):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    database.delete_camera_detection_zone(SETTINGS.database_path, camera_id, zone_id)
    return {"ok": True}

@router.post("/cameras/{camera_id}/continuous-recording")
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

@router.post("/cameras/{camera_id}/connection")
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

@router.post("/cameras/{camera_id}/delete")
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

@router.post("/cameras/{camera_id}/channels/{channel_id}")
async def update_channel(request: Request, camera_id: int, channel_id: int, name: str = Form(...), enabled: str | None = Form(None)):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_camera_channel(SETTINGS.database_path, channel_id, name=name.strip(), enabled=enabled == "on")
    _set_flash(request, "camera.channel_updated")
    return _redirect(f"/cameras/{camera_id}")
