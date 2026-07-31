"""Notification channels.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio

from fastapi import Form, Request
from fastapi.responses import HTMLResponse

from .. import database, notifications
from fastapi import APIRouter

from ..main import (
    SETTINGS,
    _notification_event_filter,
    _notification_event_templates_from_form,
    _notification_form_values,
    _pop_flash,
    _redirect,
    _require_admin,
    _set_flash,
    templates,
)

router = APIRouter()


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    channels = database.list_notification_channels(SETTINGS.database_path)
    for channel in channels:
        channel["events"] = database.list_notification_event_templates(
            SETTINGS.database_path, int(channel["id"]), channel.get("event_filter")
        )
    return templates.TemplateResponse(
        request,
        "notifications.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "channels": channels,
            "notification_event_defaults": database.notification_event_defaults(),
            "flash": _pop_flash(request),
        },
    )

@router.post("/notifications")
async def create_notification(request: Request, name: str = Form(...), kind: str = Form("webhook"), enabled: str | None = Form(None), include_snapshot: str | None = Form(None), event_filter: str = Form(""), url: str = Form(""), token: str = Form(""), chat_id: str = Form(""), email_to: str = Form(""), email_from: str = Form(""), smtp_host: str = Form(""), smtp_port: str = Form(""), smtp_username: str = Form(""), smtp_password: str = Form(""), ha_service: str = Form("")):
    guard = _require_admin(request)
    if guard:
        return guard
    form = await request.form()
    event_templates = _notification_event_templates_from_form(form)
    values = _notification_form_values(name, kind, enabled, include_snapshot, event_filter, url, token, chat_id, email_to, email_from, smtp_host, smtp_port, smtp_username, smtp_password, ha_service)
    values["event_filter"] = _notification_event_filter(event_templates)
    values["event_templates"] = event_templates
    database.create_notification_channel(SETTINGS.database_path, **values)
    _set_flash(request, "notification.created")
    return _redirect("/notifications")

@router.post("/notifications/{channel_id}")
async def update_notification(request: Request, channel_id: int, name: str = Form(...), kind: str = Form("webhook"), enabled: str | None = Form(None), include_snapshot: str | None = Form(None), event_filter: str = Form(""), url: str = Form(""), token: str = Form(""), chat_id: str = Form(""), email_to: str = Form(""), email_from: str = Form(""), smtp_host: str = Form(""), smtp_port: str = Form(""), smtp_username: str = Form(""), smtp_password: str = Form(""), ha_service: str = Form("")):
    guard = _require_admin(request)
    if guard:
        return guard
    form = await request.form()
    event_templates = _notification_event_templates_from_form(form)
    values = _notification_form_values(name, kind, enabled, include_snapshot, event_filter, url, token, chat_id, email_to, email_from, smtp_host, smtp_port, smtp_username, smtp_password, ha_service)
    values["event_filter"] = _notification_event_filter(event_templates)
    values["event_templates"] = event_templates
    database.update_notification_channel(SETTINGS.database_path, channel_id, **values)
    _set_flash(request, "notification.updated")
    return _redirect("/notifications")

@router.post("/notifications/{channel_id}/test")
async def test_notification(request: Request, channel_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    channel = next(
        (item for item in database.list_notification_channels(SETTINGS.database_path) if int(item["id"]) == channel_id),
        None,
    )
    if channel is None:
        _set_flash(request, "notification.not_found", None, "error")
        return _redirect("/notifications")
    try:
        await asyncio.to_thread(
            notifications.send_test_message, channel, public_base_url=SETTINGS.public_base_url
        )
    except Exception as exc:
        _set_flash(request, "notification.test_failed", {"error": str(exc) or exc.__class__.__name__}, "error")
    else:
        _set_flash(request, "notification.test_sent", {"name": str(channel.get("name") or "")})
    return _redirect("/notifications")

@router.post("/notifications/{channel_id}/delete")
async def delete_notification(request: Request, channel_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_notification_channel(SETTINGS.database_path, channel_id)
    _set_flash(request, "notification.deleted")
    return _redirect("/notifications")
