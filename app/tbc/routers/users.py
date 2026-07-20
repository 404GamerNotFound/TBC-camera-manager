"""User accounts.

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
    _pop_flash,
    _redirect,
    _require_admin,
    _set_flash,
    templates,
)

router = APIRouter()


@router.get("/users", response_class=HTMLResponse)
async def users(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "users": database.list_users(SETTINGS.database_path),
            "cameras": database.list_cameras(SETTINGS.database_path),
            "access_by_user": {
                user["id"]: database.list_user_camera_ids(SETTINGS.database_path, int(user["id"]))
                for user in database.list_users(SETTINGS.database_path)
            },
            "flash": _pop_flash(request),
        },
    )

@router.post("/users")
async def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("viewer"),
    camera_ids: list[int] = Form([]),
):
    guard = _require_admin(request)
    if guard:
        return guard
    user_id = database.create_user(
        SETTINGS.database_path,
        username=username.strip(),
        password=password,
        role=role,
    )
    database.set_user_camera_access(SETTINGS.database_path, user_id, camera_ids)
    audit.log_event(request, SETTINGS.database_path, "user.created", target_type="user", target_id=user_id, detail={"username": username.strip(), "role": role})
    _set_flash(request, "user.created")
    return _redirect("/users")

@router.post("/users/{user_id}")
async def update_user(
    request: Request,
    user_id: int,
    username: str = Form(...),
    role: str = Form("viewer"),
    password: str = Form(""),
    camera_ids: list[int] = Form([]),
):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_user(
        SETTINGS.database_path,
        user_id,
        username=username.strip(),
        role=role,
        password=password.strip() or None,
    )
    database.set_user_camera_access(SETTINGS.database_path, user_id, camera_ids)
    if request.session.get("user_id") == user_id:
        request.session["username"] = username.strip()
        request.session["role"] = "viewer" if role == "viewer" else "admin"
    audit.log_event(request, SETTINGS.database_path, "user.updated", target_type="user", target_id=user_id, detail={"username": username.strip(), "role": role, "password_changed": bool(password.strip())})
    _set_flash(request, "user.updated")
    return _redirect("/users")

@router.post("/users/{user_id}/delete")
async def remove_user(request: Request, user_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    if request.session.get("user_id") == user_id:
        _set_flash(request, "user.cannot_delete_self", None, "error")
        return _redirect("/users")
    database.delete_user(SETTINGS.database_path, user_id)
    audit.log_event(request, SETTINGS.database_path, "user.deleted", target_type="user", target_id=user_id)
    _set_flash(request, "user.deleted")
    return _redirect("/users")
