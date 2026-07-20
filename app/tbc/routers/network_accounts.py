"""Network provider accounts and camera-to-device mapping.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse

from .. import database
from ..network_modules import (
    NetworkAccountFieldType,
    NetworkAccountValidationError,
    NetworkConnectionError,
    get_network_module,
    list_network_module_registrations,
    normalize_account_configuration as normalize_network_account_configuration,
)
from ..network_modules.registry import UnknownNetworkModuleError
from fastapi import APIRouter

from ..main import (
    CONTROL_TIMEOUT_SECONDS,
    LOGGER,
    NETWORK_STATE_CACHE,
    SETTINGS,
    _kick_off_network_probe,
    _network_device_to_dict,
    _network_module_selector_options,
    _network_topology,
    _password_field_keys,
    _pop_flash,
    _record_network_device_status,
    _redirect,
    _require_admin,
    _set_flash,
    _t_en,
    templates,
)

router = APIRouter()


@router.get("/network-accounts", response_class=HTMLResponse)
async def network_accounts_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "network_accounts.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "network_modules": list_network_module_registrations(),
            "network_module_options": _network_module_selector_options(),
            "accounts": database.list_network_accounts(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )

@router.post("/network-accounts", response_class=HTMLResponse)
async def create_network_account_route(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    form = await request.form()
    module_key = str(form.get("module_key") or "")
    label = str(form.get("label") or "")
    try:
        network_module = get_network_module(module_key)
    except UnknownNetworkModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/network-accounts")
    try:
        config = normalize_network_account_configuration(
            network_module.account_fields,
            {
                field.key: form.get(f"account_{field.key}")
                for field in network_module.account_fields
            },
        )
    except NetworkAccountValidationError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/network-accounts")
    database.create_network_account(
        SETTINGS.database_path,
        module_key=network_module.key,
        label=label.strip() or network_module.label,
        config=config,
        sensitive_keys=_password_field_keys(network_module.account_fields),
    )
    _set_flash(request, "network_account.added")
    return _redirect("/network-accounts")

@router.get("/network-accounts/{account_id}/edit", response_class=HTMLResponse)
async def edit_network_account_page(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_network_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "network_account.not_found", None, "error")
        return _redirect("/network-accounts")
    try:
        network_module = get_network_module(account["module_key"])
    except UnknownNetworkModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/network-accounts")
    return templates.TemplateResponse(
        request,
        "network_account_edit.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "account": account,
            "network_module": network_module,
            "flash": _pop_flash(request),
        },
    )

@router.post("/network-accounts/{account_id}/edit")
async def update_network_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account = database.get_network_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "network_account.not_found", None, "error")
        return _redirect("/network-accounts")
    try:
        network_module = get_network_module(account["module_key"])
    except UnknownNetworkModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/network-accounts")
    form = await request.form()
    submitted: dict[str, Any] = {}
    for field in network_module.account_fields:
        value = form.get(f"account_{field.key}")
        if field.field_type == NetworkAccountFieldType.PASSWORD and not value:
            value = account["config"].get(field.key, "")
        submitted[field.key] = value
    try:
        config = normalize_network_account_configuration(network_module.account_fields, submitted)
    except NetworkAccountValidationError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(f"/network-accounts/{account_id}/edit")
    label = str(form.get("label") or "").strip() or network_module.label
    database.update_network_account_configuration(
        SETTINGS.database_path,
        account_id,
        label=label,
        config=config,
        sensitive_keys=_password_field_keys(network_module.account_fields),
    )
    _set_flash(request, "network_account.updated")
    return _redirect(f"/network-accounts#account-{account_id}")

@router.post("/network-accounts/{account_id}/delete")
async def delete_network_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_network_account(SETTINGS.database_path, account_id)
    NETWORK_STATE_CACHE.pop(account_id, None)
    _set_flash(request, "network_account.removed")
    return _redirect("/network-accounts")

@router.post("/network-accounts/{account_id}/test")
async def test_network_account_route(request: Request, account_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    account_url = f"/network-accounts#account-{account_id}"
    account = database.get_network_account(SETTINGS.database_path, account_id)
    if not account:
        _set_flash(request, "network_account.not_found", None, "error")
        return _redirect(account_url)
    try:
        network_module = get_network_module(account["module_key"])
    except UnknownNetworkModuleError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(account_url)
    try:
        devices = await asyncio.wait_for(
            network_module.discover_devices(account), timeout=CONTROL_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        message = _t_en("network_account.discovery_timeout", seconds=CONTROL_TIMEOUT_SECONDS)
        database.update_network_account_test_result(SETTINGS.database_path, account_id, status="error", message=message)
        _set_flash(request, "common.raw_message", {"message": message}, "error")
        return _redirect(account_url)
    except NetworkConnectionError as exc:
        database.update_network_account_test_result(SETTINGS.database_path, account_id, status="error", message=str(exc))
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(account_url)
    except Exception as exc:
        LOGGER.info("Network account test failed for %s: %s", account_id, exc)
        message = str(exc)
        database.update_network_account_test_result(SETTINGS.database_path, account_id, status="error", message=message)
        _set_flash(request, "common.raw_message", {"message": message}, "error")
        return _redirect(account_url)
    NETWORK_STATE_CACHE[account_id] = [_network_device_to_dict(device) for device in devices]
    _record_network_device_status(account_id, NETWORK_STATE_CACHE[account_id])
    message = _t_en("network_account.connected_devices_found", count=len(devices))
    database.update_network_account_test_result(SETTINGS.database_path, account_id, status="ok", message=message)
    _set_flash(request, "common.raw_message", {"message": message})
    return _redirect(account_url)

@router.get("/network-mappings", response_class=HTMLResponse)
async def network_mappings_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    accounts_by_id = {
        account["id"]: account for account in database.list_network_accounts(SETTINGS.database_path)
    }
    probed_account_ids: set[int] = set()
    mapped: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    for camera in database.list_cameras(SETTINGS.database_path):
        account_id = camera.get("network_account_id")
        mac = camera.get("network_device_mac")
        if not account_id or not mac:
            unmapped.append(camera)
            continue
        cached_devices = NETWORK_STATE_CACHE.get(account_id)
        if cached_devices is None and account_id not in probed_account_ids:
            _kick_off_network_probe(account_id)
            probed_account_ids.add(account_id)
        state = None
        if cached_devices:
            state = next(
                (device for device in cached_devices if str(device["mac_address"]).strip().lower() == mac),
                None,
            )
        camera_id = int(camera["id"])
        events = database.list_network_device_events(SETTINGS.database_path, camera_id, limit=10)
        mapped.append(
            {
                "camera": camera,
                "account": accounts_by_id.get(account_id),
                "mac": mac,
                "state": state,
                "last_status": database.get_network_device_status(SETTINGS.database_path, camera_id),
                "events": events,
            }
        )
    topology = _network_topology(mapped)
    return templates.TemplateResponse(
        request,
        "network_mappings.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "mapped": mapped,
            "unmapped": unmapped,
            "topology": topology,
            "has_network_accounts": bool(accounts_by_id),
            "flash": _pop_flash(request),
        },
    )
