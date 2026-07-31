"""Birdseye: a single server-composited mosaic stream tiling several cameras
into one ffmpeg output, distinct from the per-camera tiled wall in live.py.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio

from fastapi import Form, Request, status
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
    _pop_flash,
    _redirect,
    _require_admin,
    _require_login,
    _set_flash,
    templates,
)

router = APIRouter()

# A fixed overview-sized canvas regardless of column count keeps the
# continuous transcode cost bounded - Birdseye is meant for a glance, not
# per-camera detail (that's what /live is for).
BIRDSEYE_CANVAS_WIDTH = 1280


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
