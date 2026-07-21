"""User accounts.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import io

from fastapi import Form, Request
from fastapi.responses import HTMLResponse

from .. import audit, database, security
from fastapi import APIRouter

from ..main import (
    SETTINGS,
    _current_user,
    _pop_flash,
    _redirect,
    _require_admin,
    _require_login,
    _set_flash,
    templates,
)

router = APIRouter()


def _qr_svg(uri: str) -> str | None:
    """Render the otpauth:// URI as inline SVG via segno; None (manual secret
    entry only) if the optional dependency is missing."""
    try:
        import segno
    except ImportError:
        return None
    buffer = io.BytesIO()
    segno.make(uri, error="m").save(buffer, kind="svg", xmldecl=False, scale=4, border=2, dark="#11615c")
    return buffer.getvalue().decode("utf-8")


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

@router.post("/users/{user_id}/totp-disable")
async def admin_disable_totp(request: Request, user_id: int):
    """Admin rescue path: a user who lost both their authenticator and their
    recovery codes needs an admin to switch 2FA off for them."""
    guard = _require_admin(request)
    if guard:
        return guard
    database.set_user_totp(SETTINGS.database_path, user_id, secret=None, enabled=False)
    audit.log_event(request, SETTINGS.database_path, "user.totp_disabled_by_admin", target_type="user", target_id=user_id)
    _set_flash(request, "twofactor.disabled")
    return _redirect("/users")

@router.get("/account/2fa", response_class=HTMLResponse)
async def account_two_factor(request: Request):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    enabled = int(user.get("totp_enabled") or 0) == 1
    setup_secret = None
    provisioning_uri = None
    qr_svg = None
    if not enabled:
        setup_secret = request.session.get("totp_setup_secret")
        if not setup_secret:
            setup_secret = security.generate_totp_secret()
            request.session["totp_setup_secret"] = setup_secret
        provisioning_uri = security.totp_provisioning_uri(
            setup_secret, username=str(user["username"]), issuer=SETTINGS.app_name
        )
        qr_svg = _qr_svg(provisioning_uri)
    return templates.TemplateResponse(
        request,
        "account_2fa.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "totp_enabled": enabled,
            "setup_secret": setup_secret,
            "provisioning_uri": provisioning_uri,
            "qr_svg": qr_svg,
            "recovery_codes": None,
            "unused_recovery_codes": (
                database.count_unused_recovery_codes(SETTINGS.database_path, int(user["id"])) if enabled else 0
            ),
            "flash": _pop_flash(request),
        },
    )

@router.post("/account/2fa/enable", response_class=HTMLResponse)
async def account_two_factor_enable(request: Request, code: str = Form(...)):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    setup_secret = request.session.get("totp_setup_secret")
    if not setup_secret:
        return _redirect("/account/2fa")
    if not security.verify_totp(setup_secret, code):
        _set_flash(request, "twofactor.code_invalid", None, "error")
        return _redirect("/account/2fa")
    recovery_codes = security.generate_recovery_codes()
    database.set_user_totp(SETTINGS.database_path, int(user["id"]), secret=setup_secret, enabled=True)
    database.replace_user_recovery_codes(
        SETTINGS.database_path,
        int(user["id"]),
        [security.hash_recovery_code(recovery_code) for recovery_code in recovery_codes],
    )
    request.session.pop("totp_setup_secret", None)
    audit.log_event(request, SETTINGS.database_path, "user.totp_enabled", target_type="user", target_id=int(user["id"]))
    # The recovery codes are rendered exactly once, right now - only their
    # hashes are stored, so they cannot be shown again later.
    return templates.TemplateResponse(
        request,
        "account_2fa.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": user["role"],
            "totp_enabled": True,
            "setup_secret": None,
            "provisioning_uri": None,
            "qr_svg": None,
            "recovery_codes": recovery_codes,
            "unused_recovery_codes": len(recovery_codes),
            "flash": None,
        },
    )

@router.post("/account/2fa/disable")
async def account_two_factor_disable(request: Request, password: str = Form(...)):
    guard = _require_login(request)
    if guard:
        return guard
    user = _current_user(request)
    if database.authenticate_user(SETTINGS.database_path, str(user["username"]), password) is None:
        _set_flash(request, "twofactor.password_invalid", None, "error")
        return _redirect("/account/2fa")
    database.set_user_totp(SETTINGS.database_path, int(user["id"]), secret=None, enabled=False)
    audit.log_event(request, SETTINGS.database_path, "user.totp_disabled", target_type="user", target_id=int(user["id"]))
    _set_flash(request, "twofactor.disabled")
    return _redirect("/account/2fa")
