"""Cloud provider accounts and device import.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Form, Request
from fastapi.responses import HTMLResponse

from .. import database
from ..camera_modules import (
    get_camera_module,
)
from ..camera_modules.registry import UnknownCameraModuleError
from ..camera_modules.streams import validate_manual_stream_uri
from ..cloud_modules import (
    CloudAccountFieldType,
    CloudAccountValidationError,
    CloudConnectionError,
    CloudVerificationRequired,
    get_cloud_module,
    list_cloud_module_registrations,
    normalize_account_configuration,
)
from ..cloud_modules.registry import UnknownCloudModuleError
from fastapi import APIRouter

from ..main import (
    CONTROL_TIMEOUT_SECONDS,
    LOGGER,
    SETTINGS,
    _clear_transient_cloud_account_fields,
    _cloud_module_selector_options,
    _password_field_keys,
    _perform_cloud_account_login_attempt,
    _pop_flash,
    _redirect,
    _require_admin,
    _set_flash,
    _t_en,
    templates,
)

router = APIRouter()


@router.get("/cloud-accounts", response_class=HTMLResponse)
async def cloud_accounts_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "cloud_accounts.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "cloud_modules": list_cloud_module_registrations(),
            "cloud_module_options": _cloud_module_selector_options(),
            "accounts": database.list_cloud_accounts(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )

@router.post("/cloud-accounts", response_class=HTMLResponse)
async def create_cloud_account_route(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    form = await request.form()
    module_key = str(form.get("module_key") or "")
    label = str(form.get("label") or "")
    try:
        cloud_module = get_cloud_module(module_key)
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    try:
        config = normalize_account_configuration(
            cloud_module.account_fields,
            {
                field.key: form.get(f"account_{field.key}")
                for field in cloud_module.account_fields
            },
        )
    except CloudAccountValidationError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    database.create_cloud_account(
        SETTINGS.database_path,
        module_key=cloud_module.key,
        label=label.strip() or cloud_module.label,
        config=config,
        sensitive_keys=_password_field_keys(cloud_module.account_fields),
    )
    _set_flash(request, "cloud_account.added")
    return _redirect("/cloud-accounts")

@router.get("/cloud-accounts/{account_id}/edit", response_class=HTMLResponse)
async def edit_cloud_account_page(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    return templates.TemplateResponse(
        request,
        "cloud_account_edit.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "account": account,
            "cloud_module": cloud_module,
            "flash": _pop_flash(request),
        },
    )

@router.post("/cloud-accounts/{account_id}/edit")
async def update_cloud_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    form = await request.form()
    submitted: dict[str, Any] = {}
    for field in cloud_module.account_fields:
        value = form.get(f"account_{field.key}")
        if field.field_type == CloudAccountFieldType.PASSWORD and not value:
            value = account["config"].get(field.key, "")
        submitted[field.key] = value
    try:
        config = normalize_account_configuration(cloud_module.account_fields, submitted)
    except CloudAccountValidationError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/cloud-accounts/{account_id}/edit")
    label = str(form.get("label") or "").strip() or cloud_module.label
    database.update_cloud_account_configuration(
        SETTINGS.database_path,
        account_id,
        label=label,
        config=config,
        sensitive_keys=_password_field_keys(cloud_module.account_fields),
    )
    _set_flash(request, "cloud_account.updated")
    return _redirect(f"/cloud-accounts#account-{account_id}")

@router.post("/cloud-accounts/{account_id}/delete")
async def delete_cloud_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_cloud_account(SETTINGS.database_path, account_id)
    _set_flash(request, "cloud_account.removed")
    return _redirect("/cloud-accounts")

@router.post("/cloud-accounts/{account_id}/test")
async def test_cloud_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    account_url = f"/cloud-accounts#account-{account_id}"
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(account_url)
    return await _perform_cloud_account_login_attempt(
        request, account_id, cloud_module, account, success_redirect=account_url
    )

@router.get("/cloud-accounts/{account_id}/verify", response_class=HTMLResponse)
async def cloud_account_verify_page(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    field_key = account.get("pending_verification_field")
    if not field_key:
        _set_flash(request, "cloud_account.no_pending_verification", None, "error")
        return _redirect("/cloud-accounts")
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    field = next((item for item in cloud_module.account_fields if item.key == field_key), None)
    return templates.TemplateResponse(
        request,
        "cloud_account_verify.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "account": account,
            "cloud_module": cloud_module,
            "field": field,
            "flash": _pop_flash(request),
        },
    )

@router.post("/cloud-accounts/{account_id}/verify")
async def submit_cloud_account_verification_route(request: Request, account_id: int, code: str = Form(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    field_key = account.get("pending_verification_field")
    if not field_key:
        _set_flash(request, "cloud_account.no_pending_verification", None, "error")
        return _redirect("/cloud-accounts")
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    if not code.strip():
        _set_flash(request, "cloud_account.enter_code", None, "error")
        return _redirect(f"/cloud-accounts/{account_id}/verify")
    config = dict(account.get("config") or {})
    config[field_key] = code.strip()
    database.update_cloud_account_configuration(
        SETTINGS.database_path, account_id, label=str(account["label"]), config=config
    )
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    return await _perform_cloud_account_login_attempt(
        request,
        account_id,
        cloud_module,
        account,
        success_redirect=f"/cloud-accounts#account-{account_id}",
    )

@router.get("/cloud-accounts/{account_id}/devices", response_class=HTMLResponse)
async def cloud_account_devices_page(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_cloud_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "cloud_account.not_found", None, "error")
        return _redirect("/cloud-accounts")
    try:
        cloud_module = get_cloud_module(account["module_key"])
    except UnknownCloudModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/cloud-accounts")
    devices: list[Any] = []
    error_key: str | None = None
    error_params: dict[str, Any] = {}
    try:
        devices = await asyncio.wait_for(cloud_module.discover_devices(account), timeout=CONTROL_TIMEOUT_SECONDS)
        _clear_transient_cloud_account_fields(account_id, cloud_module)
    except asyncio.TimeoutError:
        error_key = "cloud_account.discovery_timeout"
        error_params = {"seconds": CONTROL_TIMEOUT_SECONDS}
    except CloudVerificationRequired as exc:
        database.set_cloud_account_pending_verification(
            SETTINGS.database_path, account_id, field_key=exc.field_key, message=str(exc)
        )
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/cloud-accounts/{account_id}/verify")
    except CloudConnectionError as exc:
        _clear_transient_cloud_account_fields(account_id, cloud_module)
        error_key = "common.raw_message"
        error_params = {"message": str(exc)}
    except Exception as exc:
        LOGGER.info("Cloud device discovery failed for %s: %s", account_id, exc)
        error_key = "cloud_account.discovery_failed"
        error_params = {"error": str(exc)}
    existing_uris = {
        camera.get("manual_stream_uri")
        for camera in database.list_cameras(SETTINGS.database_path)
        if camera.get("manual_stream_uri")
    }
    existing_hosts = {
        (camera.get("module_key"), camera.get("host"))
        for camera in database.list_cameras(SETTINGS.database_path)
        if camera.get("host")
    }
    return templates.TemplateResponse(
        request,
        "cloud_account_devices.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "account": account,
            "cloud_module": cloud_module,
            "devices": devices,
            "existing_uris": existing_uris,
            "existing_hosts": existing_hosts,
            "error": _t_en(error_key, **error_params) if error_key else None,
            "error_key": error_key,
            "error_params": error_params,
            "flash": _pop_flash(request),
        },
    )

@router.post("/cloud-accounts/{account_id}/devices/import")
async def import_cloud_device_route(
    request: Request,
    account_id: int,
    name: str = Form(...),
    manual_stream_uri: str | None = Form(None),
    external_id: str | None = Form(None),
    module_key: str = Form("rtsp_only"),
):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        camera_module = get_camera_module(module_key)
    except UnknownCameraModuleError:
        camera_module = get_camera_module("rtsp_only")

    host = ""
    username = ""
    password = ""
    normalized_uri = ""
    if manual_stream_uri:
        try:
            normalized_uri = validate_manual_stream_uri(manual_stream_uri)
        except ValueError as exc:
            _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
            return _redirect(f"/cloud-accounts/{account_id}/devices")
    elif external_id:
        account = database.get_cloud_account(SETTINGS.database_path, account_id)
        if not account:
            _set_flash(request, "cloud_account.not_found", None, "error")
            return _redirect("/cloud-accounts")
        try:
            cloud_module = get_cloud_module(account["module_key"])
        except UnknownCloudModuleError as exc:
            _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
            return _redirect(f"/cloud-accounts/{account_id}/devices")
        if not cloud_module.account_username_field or not cloud_module.account_password_field:
            _set_flash(request, "cloud_account.credentials_not_reusable", None, "error")
            return _redirect(f"/cloud-accounts/{account_id}/devices")
        host = external_id.strip()
        username = str(account.get(cloud_module.account_username_field) or "")
        password = str(account.get(cloud_module.account_password_field) or "")
    else:
        _set_flash(request, "cloud_account.nothing_to_import", None, "error")
        return _redirect(f"/cloud-accounts/{account_id}/devices")

    camera_id = database.create_camera(
        SETTINGS.database_path,
        name=name.strip() or "Cloud camera",
        host=host,
        onvif_port=camera_module.default_onvif_port,
        http_port=camera_module.default_http_port,
        username=username,
        password=password,
        module_key=camera_module.key,
        rtsp_port=camera_module.default_rtsp_port,
        manual_stream_uri=normalized_uri,
    )
    _set_flash(request, "camera.imported_from_cloud_account")
    return _redirect(f"/cameras/{camera_id}")
