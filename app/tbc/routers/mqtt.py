"""MQTT broker settings.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

from fastapi import Form, Request
from fastapi.responses import HTMLResponse

from .. import audit, database
from fastapi import APIRouter

from ..main import (
    SETTINGS,
    _none_if_blank,
    _pop_flash,
    _redirect,
    _require_admin,
    _set_flash,
    templates,
)

router = APIRouter()


@router.get("/mqtt", response_class=HTMLResponse)
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

@router.post("/mqtt")
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
