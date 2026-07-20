"""Session-cookie-authenticated JSON endpoints used by this app's own JS (live status/control, sd-card listing, debug log, health refresh, camera detections).

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, time
from typing import Any

from fastapi import Query, Request, status
from fastapi.responses import JSONResponse

from .. import database
from ..camera_modules import (
    CameraCapability,
    get_camera_module,
)
from ..camera_modules.registry import UnknownCameraModuleError
from ..debug_log import list_entries as list_debug_log_entries
from ..health import current_system_usage, run_health_checks
from fastapi import APIRouter

from ..main import (
    LIVE_MANAGER,
    SETTINGS,
    _current_user,
    _is_logged_in,
    _live_item_for_key,
    _live_item_payload,
    _live_items_for_user,
    _parse_date,
    _require_admin,
    _require_camera_access,
    _require_live_key_access,
    _sd_card_recording_payload,
    _start_live_item,
)

router = APIRouter()


@router.get("/api/cameras/{camera_id}/detections")
async def camera_detections_api(request: Request, camera_id: int):
    guard = _require_camera_access(request, camera_id)
    if guard:
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return {"camera_id": camera_id, "detections": database.list_detections(SETTINGS.database_path, camera_id)}

@router.get("/api/cameras/{camera_id}/detections/live")
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

@router.get("/api/sd-card/recordings")
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
        "recordings": [_sd_card_recording_payload(request, camera_id, row) for row in recordings],
        "filters": {
            "camera_id": camera_id,
            "channel": selected_channel,
            "stream": stream_value,
            "date_from": start_date.isoformat(),
            "date_to": end_date.isoformat(),
        },
    }

@router.post("/api/live/layout/item")
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

@router.get("/api/live/status")
async def live_status_api(request: Request):
    if not _is_logged_in(request):
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    user = _current_user(request)
    return {"items": [_live_item_payload(request, item) for item in _live_items_for_user(user)]}

@router.post("/api/live/start-all")
async def start_all_live_api(request: Request):
    if not _is_logged_in(request):
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    user = _current_user(request)
    items = _live_items_for_user(user)
    for item in items:
        _start_live_item(item)
    return {"items": [_live_item_payload(request, item) for item in items]}

@router.post("/api/live/{live_key}/start")
async def start_live_key_api(request: Request, live_key: str):
    guard = _require_live_key_access(request, live_key)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    user = _current_user(request)
    item = _live_item_for_key(user, live_key)
    if item is None:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    _start_live_item(item)
    return {"item": _live_item_payload(request, item)}

@router.post("/api/live/{live_key}/stop")
async def stop_live_key_api(request: Request, live_key: str):
    guard = _require_live_key_access(request, live_key)
    if guard:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    LIVE_MANAGER.stop(live_key)
    user = _current_user(request)
    item = _live_item_for_key(user, live_key)
    return {"item": _live_item_payload(request, item) if item else {"key": live_key, "status": "stopped"}}

@router.get("/api/debug-log")
async def debug_log_api(request: Request, limit: int = Query(200)):
    guard = _require_admin(request)
    if guard:
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    return {"entries": list_debug_log_entries(limit=max(1, min(600, int(limit))))}

@router.post("/api/health/refresh")
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
