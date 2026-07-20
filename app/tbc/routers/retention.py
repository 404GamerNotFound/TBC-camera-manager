"""Retention rules.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

from fastapi import Form, Request
from fastapi.responses import HTMLResponse

from .. import database
from ..camera_modules import (
    list_camera_modules,
)
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


@router.get("/retention", response_class=HTMLResponse)
async def retention_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "retention.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "rules": database.list_retention_rules(SETTINGS.database_path),
            "cameras": database.list_cameras(SETTINGS.database_path),
            "event_keys": ["continuous"]
            + sorted(
                {
                    definition.key
                    for camera_module in list_camera_modules()
                    for definition in camera_module.detection_definitions()
                }
            ),
            "flash": _pop_flash(request),
        },
    )

@router.post("/retention")
async def create_retention(request: Request, name: str = Form(...), camera_id: str = Form(""), detection_key: str = Form(""), max_age_days: str = Form(""), max_size_gb: str = Form(""), enabled: str | None = Form(None)):
    guard = _require_admin(request)
    if guard:
        return guard
    database.create_retention_rule(
        SETTINGS.database_path,
        name=name.strip(),
        enabled=enabled == "on",
        camera_id=int(camera_id) if camera_id else None,
        detection_key=_none_if_blank(detection_key),
        max_age_days=int(max_age_days) if max_age_days else None,
        max_size_gb=float(max_size_gb) if max_size_gb else None,
    )
    _set_flash(request, "retention.created")
    return _redirect("/retention")

@router.post("/retention/{rule_id}")
async def update_retention(request: Request, rule_id: int, name: str = Form(...), camera_id: str = Form(""), detection_key: str = Form(""), max_age_days: str = Form(""), max_size_gb: str = Form(""), enabled: str | None = Form(None)):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_retention_rule(
        SETTINGS.database_path,
        rule_id,
        name=name.strip(),
        enabled=enabled == "on",
        camera_id=int(camera_id) if camera_id else None,
        detection_key=_none_if_blank(detection_key),
        max_age_days=int(max_age_days) if max_age_days else None,
        max_size_gb=float(max_size_gb) if max_size_gb else None,
    )
    _set_flash(request, "retention.updated")
    return _redirect("/retention")

@router.post("/retention/{rule_id}/delete")
async def delete_retention(request: Request, rule_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_retention_rule(SETTINGS.database_path, rule_id)
    _set_flash(request, "retention.deleted")
    return _redirect("/retention")
