"""Birdseye: a single server-composited mosaic stream tiling several cameras
into one ffmpeg output, distinct from the per-camera tiled wall in live.py.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from fastapi import Form, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import audit, database
from ..camera_modules import CameraCapability
from ..live import MAX_BIRDSEYE_CAMERAS, stream_uri_for
from fastapi import APIRouter

from ..main import (
    LIVE_MANAGER,
    SETTINGS,
    _camera_supports,
    _current_user,
    _parse_date,
    _pop_flash,
    _redirect,
    _require_admin,
    _require_login,
    _set_flash,
    _timeline_payload,
    templates,
)

router = APIRouter()

# A fixed overview-sized canvas regardless of column count keeps the
# continuous transcode cost bounded - Birdseye is meant for a glance, not
# per-camera detail (that's what /live is for).
BIRDSEYE_CANVAS_WIDTH = 1280

# VOD decode of N independent players client-side is heavier than Birdseye's single composited
# live stream, so Playback mode caps lower than MAX_BIRDSEYE_CAMERAS.
MAX_PLAYBACK_CAMERAS = 9


def _birdseye_sources(camera_ids: list[int]) -> list[str]:
    sources: list[str] = []
    for camera_id in camera_ids:
        camera = database.get_camera(SETTINGS.database_path, camera_id)
        if not camera or not _camera_supports(camera, CameraCapability.LIVE):
            continue
        uri = stream_uri_for(camera)
        if uri:
            sources.append(uri)
    return sources[:MAX_BIRDSEYE_CAMERAS]


@router.get("/birdseye", response_class=HTMLResponse)
async def birdseye_view(request: Request):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    settings = database.get_birdseye_settings(SETTINGS.database_path)
    camera_ids = database.get_birdseye_camera_ids(SETTINGS.database_path)
    sources = _birdseye_sources(camera_ids)

    status_value = "disabled"
    message = ""
    is_active = settings["enabled"] and bool(sources)
    no_usable_cameras = settings["enabled"] and not sources
    if is_active:
        columns = settings["columns"]
        tile_width = BIRDSEYE_CANVAS_WIDTH // columns
        tile_height = round(tile_width * 9 / 16)
        signature = str((tuple(sorted(camera_ids)), columns, settings["fps"]))
        try:
            LIVE_MANAGER.start_composite(
                "birdseye",
                sources,
                columns=columns,
                tile_width=tile_width,
                tile_height=tile_height,
                fps=settings["fps"],
                signature=signature,
            )
            await asyncio.to_thread(LIVE_MANAGER.wait_until_ready, "birdseye", 5)
        except RuntimeError as exc:
            message = str(exc)
        status_value = LIVE_MANAGER.status("birdseye")
        message = message or LIVE_MANAGER.message("birdseye")

    cameras = database.list_cameras(SETTINGS.database_path)
    return templates.TemplateResponse(
        request,
        "birdseye.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "settings": settings,
            "selected_camera_ids": camera_ids,
            "cameras": cameras,
            "status": status_value,
            "is_active": is_active,
            "message": message,
            "no_usable_cameras": no_usable_cameras,
            "max_cameras": MAX_BIRDSEYE_CAMERAS,
            "flash": _pop_flash(request),
        },
    )


@router.get("/birdseye/playback", response_class=HTMLResponse)
async def birdseye_playback_view(request: Request, day: str | None = Query(None)):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    accessible_camera_ids = {
        int(camera["id"])
        for camera in database.list_cameras_for_user(SETTINGS.database_path, int(user["id"]), str(user["role"]))
    }
    selected_camera_ids = [
        camera_id
        for camera_id in database.get_birdseye_camera_ids(SETTINGS.database_path)
        if camera_id in accessible_camera_ids
    ][:MAX_PLAYBACK_CAMERAS]

    selected_day = _parse_date(day, date.today())
    start_at = f"{selected_day.isoformat()}T00:00:00"
    end_at = f"{(selected_day + timedelta(days=1)).isoformat()}T00:00:00"

    rows = database.list_recordings_for_cameras_range(
        SETTINGS.database_path, camera_ids=selected_camera_ids, start_at=start_at, end_at=end_at
    )
    rows_by_camera: dict[int, list[dict[str, Any]]] = {camera_id: [] for camera_id in selected_camera_ids}
    for row in rows:
        rows_by_camera.setdefault(int(row["camera_id"]), []).append(row)

    cameras: list[dict[str, Any]] = []
    timeline_data_by_camera: dict[int, dict[str, Any]] = {}
    for camera_id in selected_camera_ids:
        camera = database.get_camera(SETTINGS.database_path, camera_id)
        if not camera:
            continue
        cameras.append(camera)
        camera_rows = rows_by_camera.get(camera_id, [])
        timeline_data_by_camera[camera_id] = {
            "segments": _timeline_payload(request, (row for row in camera_rows if row["detection_key"] == "continuous")),
            "events": _timeline_payload(request, (row for row in camera_rows if row["detection_key"] != "continuous")),
        }

    return templates.TemplateResponse(
        request,
        "birdseye_playback.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "cameras": cameras,
            "timeline_data_by_camera": timeline_data_by_camera,
            "columns": database.get_birdseye_settings(SETTINGS.database_path)["columns"],
            "selected_day": selected_day.isoformat(),
            "prev_day": (selected_day - timedelta(days=1)).isoformat(),
            "next_day": (selected_day + timedelta(days=1)).isoformat(),
            "today": date.today().isoformat(),
            "is_today": selected_day == date.today(),
            "max_cameras": MAX_PLAYBACK_CAMERAS,
            "flash": _pop_flash(request),
        },
    )


@router.post("/birdseye/settings")
async def update_birdseye_settings(
    request: Request,
    enabled: str | None = Form(None),
    columns: int = Form(3),
    fps: int = Form(5),
    camera_ids: list[int] = Form([]),
):
    guard = _require_admin(request)
    if guard:
        return guard
    limited_camera_ids = camera_ids[:MAX_BIRDSEYE_CAMERAS]
    database.set_birdseye_settings(SETTINGS.database_path, enabled=enabled == "on", columns=columns, fps=fps)
    database.set_birdseye_camera_ids(SETTINGS.database_path, limited_camera_ids)
    audit.log_event(
        request,
        SETTINGS.database_path,
        "birdseye.settings_updated",
        detail={"enabled": enabled == "on", "columns": columns, "fps": fps, "camera_count": len(limited_camera_ids)},
    )
    _set_flash(request, "birdseye.settings_saved")
    return _redirect("/birdseye")


@router.post("/birdseye/stop")
async def stop_birdseye(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    LIVE_MANAGER.stop("birdseye")
    return _redirect("/birdseye")


@router.get("/birdseye/stream/index.m3u8")
async def birdseye_playlist(request: Request):
    guard = _require_login(request)
    if guard:
        return guard
    path = LIVE_MANAGER.playlist_path("birdseye")
    if not path.exists():
        return JSONResponse({"error": "not ready"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-cache"})


@router.get("/birdseye/stream/{segment}")
async def birdseye_segment(request: Request, segment: str):
    guard = _require_login(request)
    if guard:
        return guard
    if not segment.endswith(".ts") or segment.startswith("."):
        return JSONResponse({"error": "invalid segment"}, status_code=status.HTTP_404_NOT_FOUND)
    path = LIVE_MANAGER.segment_path("birdseye", segment)
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type="video/mp2t", headers={"Cache-Control": "no-cache"})
