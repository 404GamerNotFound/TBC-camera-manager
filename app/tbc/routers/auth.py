"""Login, logout, health check, and the / index redirect.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

from fastapi import Form, Request, status
from fastapi.responses import HTMLResponse

from .. import audit, database
from fastapi import APIRouter

from ..main import (
    SETTINGS,
    _is_logged_in,
    _login_lockout_remaining_seconds,
    _pop_flash,
    _redirect,
    _register_login_failure,
    _register_login_success,
    _t_en,
    templates,
)

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "tbc"}

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not _is_logged_in(request):
        return _redirect("/login")
    return _redirect("/cameras")

@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if _is_logged_in(request):
        return _redirect("/cameras")
    return templates.TemplateResponse(
        request,
        "login.html",
        {"app_name": SETTINGS.app_name, "error": None, "flash": _pop_flash(request)},
    )

@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    lockout_remaining = _login_lockout_remaining_seconds(username)
    if lockout_remaining > 0:
        audit.log_event(request, SETTINGS.database_path, "auth.login_locked_out", username_override=username.strip())
        retry_seconds = int(lockout_remaining) + 1
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "app_name": SETTINGS.app_name,
                "error": _t_en("login.locked_out", seconds=retry_seconds),
                "error_key": "login.locked_out",
                "error_params": {"seconds": retry_seconds},
                "flash": None,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_seconds)},
        )
    user = database.authenticate_user(SETTINGS.database_path, username.strip(), password)
    if user is None:
        _register_login_failure(username)
        audit.log_event(request, SETTINGS.database_path, "auth.login_failed", username_override=username.strip())
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "app_name": SETTINGS.app_name,
                "error": _t_en("login.sign_in_failed"),
                "error_key": "login.sign_in_failed",
                "error_params": {},
                "flash": None,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    _register_login_success(username)
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["role"] = user.get("role", "admin")
    audit.log_event(request, SETTINGS.database_path, "auth.login_succeeded")
    return _redirect("/cameras")

@router.post("/logout")
async def logout(request: Request):
    if _is_logged_in(request):
        audit.log_event(request, SETTINGS.database_path, "auth.logout")
    request.session.clear()
    return _redirect("/login")
