"""Clip browser, timeline, activity feed, and SD-card archive.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from .. import audit, database
from ..camera_modules import (
    CameraCapability,
    get_camera_module,
)
from ..camera_modules.registry import UnknownCameraModuleError
from ..detection.clip_backend import get_clip_encoders, rank_by_similarity
from ..recording import delete_recording_files, presigned_url, webdav_download
from fastapi import APIRouter

from ..main import (
    RECORDINGS_PAGE_SIZE,
    SETTINGS,
    _authorized_recording,
    _camera_supports,
    _current_user,
    _parse_date,
    _parse_optional_int,
    _pop_flash,
    _redirect,
    _require_admin,
    _require_camera_access,
    _require_login,
    _safe_header_filename,
    _set_flash,
    _t_en,
    _timeline_payload,
    templates,
)

router = APIRouter()

# Brute-force cosine ranking is cheap at self-hosted recording volumes, but still needs a cap so
# a huge archive can't blow up the response - ranked results are paginated the same way as the
# normal listing, just sliced out of this capped, pre-sorted list instead of a SQL LIMIT/OFFSET.
SMART_SEARCH_MAX_RESULTS = 200


def _smart_search_results(
    *, database_path: str, user: dict[str, Any], query: str, common_filters: dict[str, Any]
) -> list[dict[str, Any]] | None:
    """Returns recordings ranked by CLIP similarity to `query`, or None if semantic search
    isn't available right now (feature disabled, or the model isn't ready yet) - callers should
    fall back to the normal listing in that case."""
    settings = database.get_search_settings(database_path)
    if not settings.get("enabled"):
        return None
    encoders = get_clip_encoders(Path(SETTINGS.detection_models_path), str(settings["model_name"]))
    if encoders is None:
        return None
    _, text_encoder = encoders
    query_embedding = text_encoder.encode_text(query)
    rows = database.list_recording_embeddings(
        database_path,
        model_name=str(settings["model_name"]),
        camera_id=common_filters["camera_id"],
        detection_key=common_filters["detection_key"],
        date_from=common_filters["date_from"],
        date_to=common_filters["date_to"],
        user_id=int(user["id"]),
        role=str(user["role"]),
    )
    return [
        {"recording_id": recording_id, "similarity": score}
        for recording_id, score in rank_by_similarity(query_embedding, rows, limit=SMART_SEARCH_MAX_RESULTS)
    ]


@router.get("/recordings", response_class=HTMLResponse)
async def recordings(
    request: Request,
    camera_id: str | None = Query(None),
    detection_key: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    search: str | None = Query(None),
    sub_label: str | None = Query(None),
    sub_color: str | None = Query(None),
    smart_search: bool = Query(False),
    page: int = Query(1),
):
    guard = _require_login(request)
    if guard:
        return guard
    camera_id = _parse_optional_int(camera_id)
    user = _current_user(request)
    current_page = max(1, page)
    common_filters = {
        "camera_id": camera_id,
        "detection_key": detection_key or None,
        "date_from": date_from or None,
        "date_to": date_to or None,
        "search": search or None,
        "sub_label": sub_label or None,
        "sub_color": sub_color or None,
        "user_id": int(user["id"]),
        "role": str(user["role"]),
    }

    smart_search_unavailable = False
    ranked: list[dict[str, Any]] | None = None
    if smart_search and search:
        ranked = await asyncio.to_thread(
            _smart_search_results,
            database_path=SETTINGS.database_path,
            user=user,
            query=search,
            common_filters=common_filters,
        )
        smart_search_unavailable = ranked is None

    if ranked is not None:
        total = len(ranked)
        total_pages = max(1, math.ceil(total / RECORDINGS_PAGE_SIZE))
        current_page = min(current_page, total_pages)
        page_slice = ranked[(current_page - 1) * RECORDINGS_PAGE_SIZE : current_page * RECORDINGS_PAGE_SIZE]
        similarity_by_id = {item["recording_id"]: item["similarity"] for item in page_slice}
        rows = []
        for item in page_slice:
            row = database.get_recording(SETTINGS.database_path, item["recording_id"])
            if row is not None:
                row = {**row, "similarity": similarity_by_id[item["recording_id"]]}
                rows.append(row)
    else:
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
            "sub_labels": database.list_recording_sub_labels(SETTINGS.database_path),
            "sub_colors": database.list_recording_sub_colors(SETTINGS.database_path),
            "search_enabled": bool(database.get_search_settings(SETTINGS.database_path).get("enabled")),
            "smart_search_unavailable": smart_search_unavailable,
            "filters": {
                "camera_id": camera_id,
                "detection_key": detection_key or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
                "search": search or "",
                "sub_label": sub_label or "",
                "sub_color": sub_color or "",
                "smart_search": smart_search,
            },
            "total": total,
            "page": current_page,
            "total_pages": total_pages,
            "page_size": RECORDINGS_PAGE_SIZE,
            "flash": _pop_flash(request),
        },
    )

@router.get("/timeline", response_class=HTMLResponse)
async def timeline_view(
    request: Request,
    camera_id: str | None = Query(None),
    day: str | None = Query(None),
):
    guard = _require_login(request)
    if guard:
        return guard
    camera_id = _parse_optional_int(camera_id)
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
        timeline_segments = _timeline_payload(request, (row for row in rows if row["detection_key"] == "continuous"))
        timeline_events = _timeline_payload(request, (row for row in rows if row["detection_key"] != "continuous"))

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

@router.get("/activity", response_class=HTMLResponse)
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
            "events": _timeline_payload(request, events_by_camera.get(int(camera["id"]), [])),
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

@router.get("/sd-card", response_class=HTMLResponse)
async def sd_card(
    request: Request,
    camera_id: str | None = Query(None),
    channel: int | None = Query(None),
    stream: str = Query("main"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    guard = _require_login(request)
    if guard:
        return guard
    camera_id = _parse_optional_int(camera_id)
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

@router.get("/sd-card/{camera_id}/media")
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

def _webdav_stream_response(recording: dict[str, Any], *, snapshot: bool = False, disposition: str = "inline") -> StreamingResponse | None:
    """Proxies a WebDAV-backed recording/snapshot through the app - WebDAV has no
    presigned-URL concept to redirect the browser to (see recording.webdav_download)."""
    result = webdav_download(recording, snapshot=snapshot)
    if not result:
        return None
    chunks, content_length, content_type = result
    default_name = "snapshot.jpg" if snapshot else (recording.get("file_name") or "clip.mp4")
    headers = {"Content-Disposition": f'{disposition}; filename="{_safe_header_filename(default_name)}"'}
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    return StreamingResponse(chunks, media_type=content_type, headers=headers)

@router.get("/recordings/{recording_id}/media")
async def recording_media(request: Request, recording_id: int):
    recording = _authorized_recording(request, recording_id)
    if not recording:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    local_path = recording.get("local_path")
    if local_path and Path(local_path).exists():
        # content_disposition_type="inline" is required here, not just cosmetic:
        # FileResponse's default ("attachment") makes Safari in particular
        # refuse to play the file in a <video> tag at all - it fetches the
        # bytes (still 206 Partial Content) but never hands them to the
        # decoder, since the header says "save this", not "render this".
        # /download below is the one that should keep the attachment default.
        return FileResponse(
            local_path,
            media_type="video/mp4",
            filename=recording.get("file_name") or "clip.mp4",
            content_disposition_type="inline",
        )
    url = presigned_url(recording)
    if url:
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    webdav_response = _webdav_stream_response(recording, disposition="inline")
    if webdav_response:
        return webdav_response
    return JSONResponse({"error": "media not available"}, status_code=status.HTTP_404_NOT_FOUND)

@router.get("/recordings/{recording_id}/snapshot")
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
    webdav_response = _webdav_stream_response(recording, snapshot=True, disposition="inline")
    if webdav_response:
        return webdav_response
    return JSONResponse({"error": "snapshot not available"}, status_code=status.HTTP_404_NOT_FOUND)

@router.get("/recordings/{recording_id}/download")
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
    webdav_response = _webdav_stream_response(recording, disposition="attachment")
    if webdav_response:
        return webdav_response
    return JSONResponse({"error": "download not available"}, status_code=status.HTTP_404_NOT_FOUND)

@router.post("/recordings/{recording_id}/delete")
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

@router.post("/recordings/{recording_id}/lock")
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

@router.post("/recordings/{recording_id}/unlock")
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
