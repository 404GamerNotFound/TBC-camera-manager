"""Live-view pages, layout, and HLS/WebRTC playback endpoints.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio

from fastapi import Form, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from .. import database
from ..camera_modules import (
    CameraCapability,
)
from ..live import stream_uri_for
from fastapi import APIRouter

from ..main import (
    GO2RTC_MANAGER,
    LIVE_MANAGER,
    LOGGER,
    SETTINGS,
    _camera_supports,
    _current_user,
    _live_item_for_key,
    _live_item_payload,
    _live_items_for_user,
    _pop_flash,
    _redirect,
    _refresh_camera,
    _require_admin,
    _require_camera_access,
    _require_live_key_access,
    _require_login,
    _set_flash,
    _start_live_item,
    templates,
)

router = APIRouter()


@router.get("/live", response_class=HTMLResponse)
async def live_view(request: Request):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    live_items = _live_items_for_user(user)
    # Starting the streams here makes the wall independent of a follow-up
    # browser POST. That POST can be lost by an Android WebView/PWA or an
    # Ingress token transition even though the page request itself reached
    # TBC successfully. The old browser-side start-all endpoint had exactly
    # that failure mode. Starting is idempotent for an already-running item.
    for item in live_items:
        _start_live_item(item)
    await asyncio.gather(
        *(
            asyncio.to_thread(LIVE_MANAGER.wait_until_ready, str(item["key"]), 5)
            for item in live_items
            if item.get("stream_uri")
        )
    )
    return templates.TemplateResponse(
        request,
        "live.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "live_items": [_live_item_payload(request, item) for item in live_items],
            "wall_settings": database.get_live_wall_settings(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )

@router.post("/live/layout")
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

@router.post("/live/camera/{camera_id}/start")
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

@router.post("/live/channel/{channel_id}/start")
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

@router.post("/live/{live_key}/stop")
async def stop_live(request: Request, live_key: str):
    guard = _require_login(request)
    if guard:
        return guard
    LIVE_MANAGER.stop(live_key)
    return _redirect("/live")

@router.get("/live/{live_key}/index.m3u8")
async def live_playlist(request: Request, live_key: str):
    guard = _require_live_key_access(request, live_key)
    if guard:
        return guard
    path = LIVE_MANAGER.playlist_path(live_key)
    if not path.exists():
        return JSONResponse({"error": "not ready"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-cache"})

@router.get("/live/{live_key}/{segment}")
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

@router.post("/live/{live_key}/webrtc/offer")
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
