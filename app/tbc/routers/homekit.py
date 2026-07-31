"""Apple HomeKit settings (live view only, via HAP-python - see app/tbc/homekit.py
and app/tbc/homekit_worker.py for the accessory bridge subprocess itself).

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import io

from fastapi import Form, Request
from fastapi.responses import HTMLResponse

from .. import audit, database
from ..homekit import MAX_HOMEKIT_CAMERAS
from fastapi import APIRouter

from ..main import (
    HOMEKIT_MANAGER,
    SETTINGS,
    _homekit_camera_configs,
    _pop_flash,
    _redirect,
    _require_admin,
    _set_flash,
    templates,
)

router = APIRouter()


def _qr_svg(uri: str) -> str | None:
    """Render the pairing URI as inline SVG via segno; None if the optional
    dependency is missing. Duplicated from routers/users.py's TOTP-setup
    helper of the same name rather than imported across router modules."""
    try:
        import segno
    except ImportError:
        return None
    buffer = io.BytesIO()
    segno.make(uri, error="m").save(buffer, kind="svg", xmldecl=False, scale=4, border=2, dark="#11615c")
    return buffer.getvalue().decode("utf-8")


def _start_if_enabled(settings: dict) -> None:
    """Starts the bridge if HomeKit is enabled with at least one usable
    camera. Callers are always in a "the bridge must not be using stale
    config/state" situation (settings just changed, or pairing was just
    reset) and so always call HOMEKIT_MANAGER.stop() themselves first - not
    duplicated here. Raises RuntimeError (from HOMEKIT_MANAGER.start(), e.g.
    ffmpeg missing) so callers can surface it as a flash message instead of
    it being silently swallowed."""
    if not settings["enabled"]:
        return
    camera_aids = database.get_homekit_camera_aids(SETTINGS.database_path)
    configs = _homekit_camera_configs(camera_aids)
    if not configs:
        return
    HOMEKIT_MANAGER.start(configs, settings["pincode"])


@router.get("/homekit", response_class=HTMLResponse)
async def homekit_settings(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    settings = database.get_homekit_settings(SETTINGS.database_path)
    camera_aids = database.get_homekit_camera_aids(SETTINGS.database_path)
    cameras = database.list_cameras(SETTINGS.database_path)
    pairing = HOMEKIT_MANAGER.pairing_info()
    no_usable_cameras = settings["enabled"] and not _homekit_camera_configs(camera_aids)
    return templates.TemplateResponse(
        request,
        "homekit.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "settings": settings,
            "selected_camera_ids": set(camera_aids.keys()),
            "cameras": cameras,
            "status": HOMEKIT_MANAGER.status(),
            "message": HOMEKIT_MANAGER.message(),
            "pairing": pairing,
            "qr_svg": _qr_svg(pairing["xhm_uri"]) if pairing["xhm_uri"] else None,
            "no_usable_cameras": no_usable_cameras,
            "max_cameras": MAX_HOMEKIT_CAMERAS,
            "flash": _pop_flash(request),
        },
    )


@router.post("/homekit/settings")
async def update_homekit_settings(
    request: Request,
    enabled: str | None = Form(None),
    camera_ids: list[int] = Form([]),
):
    guard = _require_admin(request)
    if guard:
        return guard
    limited_camera_ids = camera_ids[:MAX_HOMEKIT_CAMERAS]
    HOMEKIT_MANAGER.stop()
    database.set_homekit_enabled(SETTINGS.database_path, enabled == "on")
    database.set_homekit_camera_ids(SETTINGS.database_path, limited_camera_ids)
    settings = database.get_homekit_settings(SETTINGS.database_path)
    try:
        _start_if_enabled(settings)
    except RuntimeError as exc:
        _set_flash(request, "homekit.start_failed", {"error": str(exc)}, "error")
        return _redirect("/homekit")
    audit.log_event(
        request,
        SETTINGS.database_path,
        "homekit.settings_updated",
        detail={"enabled": settings["enabled"], "camera_count": len(limited_camera_ids)},
    )
    _set_flash(request, "homekit.settings_saved")
    return _redirect("/homekit")


@router.post("/homekit/reset-pairing")
async def reset_homekit_pairing(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    HOMEKIT_MANAGER.stop()
    HOMEKIT_MANAGER.reset_pairing()
    settings = database.get_homekit_settings(SETTINGS.database_path)
    try:
        _start_if_enabled(settings)
    except RuntimeError as exc:
        _set_flash(request, "homekit.start_failed", {"error": str(exc)}, "error")
        return _redirect("/homekit")
    audit.log_event(request, SETTINGS.database_path, "homekit.pairing_reset")
    _set_flash(request, "homekit.pairing_reset")
    return _redirect("/homekit")
