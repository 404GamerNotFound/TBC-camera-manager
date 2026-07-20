"""The public, API-key-secured read/control API for external integrations (/api/v1/...).

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from .. import __version__, audit, database
from ..api_common import (
    camera_public_dict as _camera_public_dict,
    recording_public_dict as _recording_public_dict,
    storage_public_dict as _storage_public_dict,
)
from ..detection import factory as detection_factory
from ..health import current_system_usage
from ..live import stream_uri_for
from ..recording import presigned_url
from fastapi import APIRouter

from ..main import (
    APP_UPDATE_STATE,
    LIVE_MANAGER,
    SETTINGS,
    SNAPSHOT_MANAGER,
    SNAPSHOT_SEMAPHORE,
    _api_stream_key,
    _api_token_username,
    _detection_settings_public_dict,
    _parse_date,
    _require_api_key,
    _require_api_key_control,
    _require_api_key_stream,
    _resolve_api_stream_uri,
    _rewrite_playlist_with_auth,
)

router = APIRouter()


@router.get("/api/v1/status")
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

@router.get("/api/v1/cameras")
async def api_v1_cameras(request: Request):
    guard = _require_api_key(request)
    if guard:
        return guard
    cameras = database.list_cameras(SETTINGS.database_path)
    return {"cameras": [_camera_public_dict(camera) for camera in cameras]}

@router.get("/api/v1/cameras/{camera_id}")
async def api_v1_camera_detail(request: Request, camera_id: int):
    guard = _require_api_key(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return _camera_public_dict(camera)

@router.get("/api/v1/cameras/{camera_id}/snapshot")
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

@router.get("/api/v1/cameras/{camera_id}/detections")
async def api_v1_camera_detections(request: Request, camera_id: int):
    guard = _require_api_key(request)
    if guard:
        return guard
    camera = database.get_camera(SETTINGS.database_path, camera_id)
    if not camera:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    detections = database.list_detections(SETTINGS.database_path, camera_id)
    return {"camera_id": camera_id, "detections": detections}

@router.get("/api/v1/cameras/{camera_id}/detection-settings")
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

@router.post("/api/v1/cameras/{camera_id}/recording")
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

@router.post("/api/v1/cameras/{camera_id}/continuous-recording")
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

@router.post("/api/v1/cameras/{camera_id}/detection")
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

@router.get("/api/v1/cameras/{camera_id}/stream/index.m3u8")
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

@router.get("/api/v1/cameras/{camera_id}/stream/{segment}")
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

@router.post("/api/v1/cameras/{camera_id}/stream/stop")
async def api_v1_camera_stream_stop(request: Request, camera_id: int):
    guard = _require_api_key_stream(request)
    if guard:
        return guard
    LIVE_MANAGER.stop(_api_stream_key(camera_id))
    return {"status": "stopped"}

@router.get("/api/v1/recordings")
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

@router.get("/api/v1/recordings/{recording_id}")
async def api_v1_recording_detail(request: Request, recording_id: int):
    guard = _require_api_key(request)
    if guard:
        return guard
    recording = database.get_recording(SETTINGS.database_path, recording_id)
    if not recording:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return _recording_public_dict(recording)

@router.get("/api/v1/recordings/{recording_id}/media")
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

@router.get("/api/v1/recordings/{recording_id}/snapshot")
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

@router.get("/api/v1/activity")
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

@router.get("/api/v1/storage")
async def api_v1_storage(request: Request):
    guard = _require_api_key(request)
    if guard:
        return guard
    targets = database.list_storage_targets(SETTINGS.database_path)
    return {"storage_targets": [_storage_public_dict(target) for target in targets]}

@router.get("/api/v1/health")
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
