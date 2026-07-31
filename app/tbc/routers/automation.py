"""Automation rules.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

from fastapi import Form, Request
from fastapi.responses import HTMLResponse

from .. import automation, database, notifications
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

RECORDING_EVENT_TYPES = ("recording_started", "recording_finished", "recording_failed", "recording_skipped")


def _automation_rule_values(
    *,
    name: str,
    enabled: str | None,
    source: str,
    camera_id: str,
    event_type: str,
    kind: str,
    identity: str,
    cooldown_seconds: str,
    notification_channel_id: str,
    title_template: str,
    message_template: str,
) -> dict:
    matched_face_id, matched_plate_id, unknown_only = automation.parse_identity_filter(identity)
    is_recording = source == "recording_event"
    return {
        "name": name.strip(),
        "enabled": enabled == "on",
        "source": source,
        "camera_id": int(camera_id) if camera_id else None,
        "event_type": _none_if_blank(event_type) if is_recording else None,
        "kind": None if is_recording else _none_if_blank(kind),
        "matched_face_id": None if is_recording else matched_face_id,
        "matched_plate_id": None if is_recording else matched_plate_id,
        "unknown_only": False if is_recording else unknown_only,
        "cooldown_seconds": int(cooldown_seconds) if cooldown_seconds else 0,
        "notification_channel_id": int(notification_channel_id),
        "title_template": title_template.strip() or "{{ title }}",
        "message_template": message_template.strip() or "{{ message }}",
    }


@router.get("/automations", response_class=HTMLResponse)
async def automations_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "automation.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "rules": database.list_automation_rules(SETTINGS.database_path),
            "cameras": database.list_cameras(SETTINGS.database_path),
            "channels": database.list_notification_channels(SETTINGS.database_path),
            "known_faces": database.list_known_faces(SETTINGS.database_path),
            "known_plates": database.list_known_plates(SETTINGS.database_path),
            "recording_event_types": RECORDING_EVENT_TYPES,
            "flash": _pop_flash(request),
        },
    )


@router.post("/automations")
async def create_automation(
    request: Request,
    name: str = Form(...),
    enabled: str | None = Form(None),
    source: str = Form("recording_event"),
    camera_id: str = Form(""),
    event_type: str = Form(""),
    kind: str = Form(""),
    identity: str = Form(""),
    cooldown_seconds: str = Form("0"),
    notification_channel_id: str = Form(...),
    title_template: str = Form("{{ title }}"),
    message_template: str = Form("{{ message }}"),
):
    guard = _require_admin(request)
    if guard:
        return guard
    values = _automation_rule_values(
        name=name,
        enabled=enabled,
        source=source,
        camera_id=camera_id,
        event_type=event_type,
        kind=kind,
        identity=identity,
        cooldown_seconds=cooldown_seconds,
        notification_channel_id=notification_channel_id,
        title_template=title_template,
        message_template=message_template,
    )
    database.create_automation_rule(SETTINGS.database_path, **values)
    _set_flash(request, "automation.created")
    return _redirect("/automations")


@router.post("/automations/{rule_id}")
async def update_automation(
    request: Request,
    rule_id: int,
    name: str = Form(...),
    enabled: str | None = Form(None),
    source: str = Form("recording_event"),
    camera_id: str = Form(""),
    event_type: str = Form(""),
    kind: str = Form(""),
    identity: str = Form(""),
    cooldown_seconds: str = Form("0"),
    notification_channel_id: str = Form(...),
    title_template: str = Form("{{ title }}"),
    message_template: str = Form("{{ message }}"),
):
    guard = _require_admin(request)
    if guard:
        return guard
    values = _automation_rule_values(
        name=name,
        enabled=enabled,
        source=source,
        camera_id=camera_id,
        event_type=event_type,
        kind=kind,
        identity=identity,
        cooldown_seconds=cooldown_seconds,
        notification_channel_id=notification_channel_id,
        title_template=title_template,
        message_template=message_template,
    )
    database.update_automation_rule(SETTINGS.database_path, rule_id, **values)
    _set_flash(request, "automation.updated")
    return _redirect("/automations")


@router.post("/automations/{rule_id}/test")
async def test_automation(request: Request, rule_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    rule = database.get_automation_rule(SETTINGS.database_path, rule_id)
    channel = (
        database.get_notification_channel(SETTINGS.database_path, int(rule["notification_channel_id"]))
        if rule
        else None
    )
    if channel is None:
        _set_flash(request, "automation.not_found", None, "error")
        return _redirect("/automations")
    try:
        notifications.send_via_channel(
            channel,
            "TBC automation test",
            f"Test firing of automation rule \"{rule['name']}\".",
            public_base_url=SETTINGS.public_base_url,
        )
    except Exception as exc:
        _set_flash(request, "automation.test_failed", {"error": str(exc) or exc.__class__.__name__}, "error")
    else:
        _set_flash(request, "automation.test_sent", {"name": str(rule.get("name") or "")})
    return _redirect("/automations")


@router.post("/automations/{rule_id}/delete")
async def delete_automation(request: Request, rule_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_automation_rule(SETTINGS.database_path, rule_id)
    _set_flash(request, "automation.deleted")
    return _redirect("/automations")
