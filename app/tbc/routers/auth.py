"""Login, logout, health check, and the / index redirect.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Form, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import audit, database, security
from fastapi import APIRouter

from ..main import (
    SETTINGS,
    _is_logged_in,
    _login_lockout_remaining_seconds,
    _pop_flash,
    _redirect,
    _register_login_failure,
    _register_login_success,
    _require_admin,
    _set_flash,
    _t_en,
    templates,
)

router = APIRouter()

# The initial admin password every fresh install ships with unless the
# TBC_ADMIN_PASSWORD env var / HA option was set (see config.load_settings).
DEFAULT_ADMIN_PASSWORD = "bitte-aendern"


def _post_login_redirect(user: dict) -> str:
    """First admin sign-in on an empty install lands on the setup guide
    instead of a blank camera list; everyone else goes straight to /cameras."""
    if str(user.get("role") or "admin") != "admin":
        return "/cameras"
    if database.get_onboarding_dismissed(SETTINGS.database_path):
        return "/cameras"
    if database.list_cameras(SETTINGS.database_path):
        return "/cameras"
    return "/onboarding"


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "tbc"}

_ICONS_DIR = Path(__file__).resolve().parents[1] / "static" / "icons"


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(_ICONS_DIR / "icon-192.png", media_type="image/png")

@router.get("/manifest.webmanifest", include_in_schema=False)
async def webmanifest(request: Request):
    """PWA manifest, built per-request because every URL needs the Ingress
    prefix baked in when TBC runs inside Home Assistant (see app/tbc/ingress.py -
    the middleware only rewrites headers, not JSON bodies)."""
    prefix = request.state.ingress_prefix
    return JSONResponse(
        {
            "name": f"{SETTINGS.app_name} Camera Manager",
            "short_name": SETTINGS.app_name,
            "description": "Modular camera manager for ONVIF and RTSP cameras",
            "start_url": f"{prefix}/cameras",
            "scope": f"{prefix}/",
            "display": "standalone",
            "orientation": "any",
            "background_color": "#f6f7f4",
            "theme_color": "#11615c",
            "icons": [
                {"src": f"{prefix}/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": f"{prefix}/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
                {
                    "src": f"{prefix}/static/icons/icon-maskable-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ],
        },
        media_type="application/manifest+json",
    )

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
    if int(user.get("totp_enabled") or 0) == 1:
        # Password verified, but the session is not authenticated yet - only a
        # pending marker is stored, and the lockout counter stays armed so 2FA
        # codes can't be brute-forced any faster than passwords.
        request.session.clear()
        request.session["pending_2fa_user_id"] = user["id"]
        return _redirect("/login/2fa")
    _register_login_success(username)
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["role"] = user.get("role", "admin")
    audit.log_event(request, SETTINGS.database_path, "auth.login_succeeded")
    return _redirect(_post_login_redirect(user))

@router.get("/login/2fa", response_class=HTMLResponse)
async def two_factor_form(request: Request):
    if not request.session.get("pending_2fa_user_id"):
        return _redirect("/login")
    return templates.TemplateResponse(
        request,
        "login_2fa.html",
        {"app_name": SETTINGS.app_name, "error": None, "flash": None},
    )

@router.post("/login/2fa", response_class=HTMLResponse)
async def two_factor_verify(request: Request, code: str = Form(...)):
    pending_id = request.session.get("pending_2fa_user_id")
    if not pending_id:
        return _redirect("/login")
    user = database.get_user(SETTINGS.database_path, int(pending_id))
    if user is None or int(user.get("totp_enabled") or 0) != 1:
        request.session.clear()
        return _redirect("/login")
    username = str(user["username"])
    lockout_remaining = _login_lockout_remaining_seconds(username)
    if lockout_remaining > 0:
        audit.log_event(request, SETTINGS.database_path, "auth.login_locked_out", username_override=username)
        retry_seconds = int(lockout_remaining) + 1
        return templates.TemplateResponse(
            request,
            "login_2fa.html",
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
    normalized = code.strip()
    accepted = security.verify_totp(str(user.get("totp_secret") or ""), normalized)
    if not accepted and "-" in normalized:
        accepted = database.consume_recovery_code(
            SETTINGS.database_path, int(user["id"]), security.hash_recovery_code(normalized)
        )
        if accepted:
            audit.log_event(request, SETTINGS.database_path, "auth.recovery_code_used", username_override=username)
    if not accepted:
        _register_login_failure(username)
        audit.log_event(request, SETTINGS.database_path, "auth.two_factor_failed", username_override=username)
        return templates.TemplateResponse(
            request,
            "login_2fa.html",
            {
                "app_name": SETTINGS.app_name,
                "error": _t_en("login.two_factor_failed"),
                "error_key": "login.two_factor_failed",
                "error_params": {},
                "flash": None,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    _register_login_success(username)
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["username"] = username
    request.session["role"] = user.get("role", "admin")
    audit.log_event(request, SETTINGS.database_path, "auth.login_succeeded")
    return _redirect(_post_login_redirect(user))

@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    cameras = database.list_cameras(SETTINGS.database_path)
    # Checked against the actual stored hash, not SETTINGS.admin_password (loaded
    # once from the env var at startup and never updated in-process) - otherwise
    # this step would still read "open" right after the form below fixes it.
    still_default = (
        database.authenticate_user(SETTINGS.database_path, str(request.session.get("username")), DEFAULT_ADMIN_PASSWORD)
        is not None
    )
    return templates.TemplateResponse(
        request,
        "onboarding.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "password_is_default": still_default,
            "camera_count": len(cameras),
            "first_camera_id": int(cameras[0]["id"]) if cameras else None,
            "triggers_configured": database.any_recording_triggers_configured(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )

@router.post("/onboarding/password")
async def onboarding_password(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    guard = _require_admin(request)
    if guard:
        return guard
    if new_password != confirm_password:
        _set_flash(request, "onboarding.password_mismatch", None, "error")
        return _redirect("/onboarding")
    if len(new_password) < 8 or new_password == DEFAULT_ADMIN_PASSWORD:
        _set_flash(request, "onboarding.password_too_weak", None, "error")
        return _redirect("/onboarding")
    user_id = int(request.session["user_id"])
    user = database.get_user(SETTINGS.database_path, user_id)
    database.update_user(
        SETTINGS.database_path,
        user_id,
        username=str(user["username"]),
        role=str(user.get("role") or "admin"),
        password=new_password,
    )
    audit.log_event(request, SETTINGS.database_path, "user.updated", target_type="user", target_id=user_id, detail={"password_changed": True, "source": "onboarding"})
    _set_flash(request, "onboarding.password_changed")
    return _redirect("/onboarding")

@router.post("/onboarding/dismiss")
async def onboarding_dismiss(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    database.set_onboarding_dismissed(SETTINGS.database_path, True)
    return _redirect("/cameras")

@router.post("/logout")
async def logout(request: Request):
    if _is_logged_in(request):
        audit.log_event(request, SETTINGS.database_path, "auth.logout")
    request.session.clear()
    return _redirect("/login")
