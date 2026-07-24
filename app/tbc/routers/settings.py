"""General settings, backup/restore, audit log, and API access/tokens.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

from fastapi import File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .. import audit, backup, database
from ..debug_log import clear_entries as clear_debug_log_entries
from ..debug_log import list_entries as list_debug_log_entries
from ..security import generate_api_key, hash_api_key
from fastapi import APIRouter

from ..main import (
    SETTINGS,
    _api_examples,
    _current_user,
    _mcp_tool_examples,
    _none_if_blank,
    _pop_flash,
    _redirect,
    _require_admin,
    _set_flash,
    templates,
)

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "debug_count": len(list_debug_log_entries(limit=600)),
            "ui_preferences": database.get_ui_preferences(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )

@router.get("/settings/audit-log", response_class=HTMLResponse)
async def audit_log_page(request: Request, page: int = Query(1, ge=1), action: str | None = Query(None)):
    guard = _require_admin(request)
    if guard:
        return guard
    page_size = 50
    result = database.list_audit_events(
        SETTINGS.database_path,
        limit=page_size,
        offset=(page - 1) * page_size,
        action=_none_if_blank(action) if action else None,
    )
    total_pages = max(1, (result["total"] + page_size - 1) // page_size)
    return templates.TemplateResponse(
        request,
        "audit_log.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "events": result["events"],
            "total": result["total"],
            "page": page,
            "total_pages": total_pages,
            "selected_action": action or "",
            "actions": database.list_distinct_audit_actions(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )

@router.get("/settings/backup", response_class=HTMLResponse)
async def backup_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "backup.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "backups": backup.list_backup_files(SETTINGS.backups_path),
            "backup_schedule": database.get_backup_schedule(SETTINGS.database_path),
            "storage_targets": database.list_storage_targets(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )

@router.post("/settings/backup/create")
async def create_backup_route(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        saved_backup = backup.create_backup_file(
            SETTINGS.database_path,
            SETTINGS.secret_key,
            SETTINGS.backups_path,
        )
    except backup.BackupError as exc:
        _set_flash(request, "backup.create_failed", {"error": exc}, "error")
    else:
        audit.log_event(
            request,
            SETTINGS.database_path,
            "backup.created",
            target_type="backup",
            target_id=saved_backup.name,
        )
        _set_flash(request, "backup.created", {"filename": saved_backup.name})
    return _redirect("/settings/backup")


@router.post("/settings/backup/schedule")
async def update_backup_schedule_route(
    request: Request,
    enabled: str | None = Form(None),
    interval_hours: int = Form(24),
    retain_count: int = Form(7),
    storage_id: str = Form(""),
):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        selected_storage_id = int(storage_id) if storage_id.strip() else None
        if selected_storage_id is not None and database.get_storage_target(
            SETTINGS.database_path, selected_storage_id
        ) is None:
            raise ValueError("The selected external storage target does not exist.")
        database.update_backup_schedule(
            SETTINGS.database_path,
            enabled=enabled is not None,
            interval_hours=interval_hours,
            retain_count=retain_count,
            storage_id=selected_storage_id,
        )
    except (TypeError, ValueError) as exc:
        _set_flash(request, "backup.schedule_failed", {"error": str(exc)}, "error")
    else:
        audit.log_event(
            request,
            SETTINGS.database_path,
            "backup.schedule_updated",
            target_type="backup_schedule",
        )
        _set_flash(request, "backup.schedule_saved")
    return _redirect("/settings/backup")


@router.get("/settings/backup/download/{filename}")
async def download_backup_route(request: Request, filename: str):
    guard = _require_admin(request)
    if guard:
        return guard
    backup_file = backup.get_backup_file(SETTINGS.backups_path, filename)
    if backup_file is None:
        raise HTTPException(status_code=404, detail="Backup file not found")
    audit.log_event(
        request,
        SETTINGS.database_path,
        "backup.downloaded",
        target_type="backup",
        target_id=backup_file.name,
    )
    return FileResponse(
        backup_file,
        media_type="application/octet-stream",
        filename=backup_file.name,
    )

@router.post("/settings/backup/restore")
async def restore_backup_route(request: Request, backup_file: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        data = await backup_file.read(500 * 1024 * 1024 + 1)
        backup.restore_backup(data, SETTINGS.database_path, SETTINGS.secret_key)
        audit.log_event(request, SETTINGS.database_path, "backup.restored")
        _set_flash(request, "backup.restore_succeeded")
    except backup.BackupError as exc:
        _set_flash(request, "backup.restore_failed", {"error": exc}, "error")
    finally:
        await backup_file.close()
    return _redirect("/settings/backup")

@router.get("/api-access", response_class=HTMLResponse)
async def api_access_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "api_access.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "api_config": database.get_api_config(SETTINGS.database_path),
            "api_tokens": database.list_api_tokens(SETTINGS.database_path),
            "mcp_endpoint_url": f"{str(request.base_url).rstrip('/')}/mcp/mcp",
            "api_examples": _api_examples(),
            "mcp_tools": _mcp_tool_examples(),
            "flash": _pop_flash(request),
        },
    )

@router.post("/settings/api")
async def update_api_settings(
    request: Request,
    enabled: str | None = Form(None),
    require_api_key: str | None = Form(None),
):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_api_config(
        SETTINGS.database_path,
        enabled=enabled == "on",
        require_api_key=require_api_key == "on",
    )
    audit.log_event(request, SETTINGS.database_path, "api.settings_updated", detail={"enabled": enabled == "on", "require_api_key": require_api_key == "on"})
    _set_flash(request, "api.settings_saved")
    return _redirect("/api-access")

@router.post("/settings/api-tokens")
async def create_api_token_route(request: Request, name: str = Form(...), can_control: str | None = Form(None)):
    guard = _require_admin(request)
    if guard:
        return guard
    user = _current_user(request)
    key = generate_api_key()
    control = can_control == "on"
    token_id = database.create_api_token(
        SETTINGS.database_path,
        name=name.strip() or "API token",
        key_hash=hash_api_key(key),
        key_prefix=key[:12],
        created_by_user_id=int(user["id"]),
        can_control=control,
    )
    audit.log_event(request, SETTINGS.database_path, "api_token.created", target_type="api_token", target_id=token_id, detail={"name": name, "can_control": control})
    _set_flash(request, "api.key_generated", {"key": key})
    return _redirect("/api-access")

@router.post("/settings/api-tokens/{token_id}/revoke")
async def revoke_api_token_route(request: Request, token_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.revoke_api_token(SETTINGS.database_path, token_id)
    audit.log_event(request, SETTINGS.database_path, "api_token.revoked", target_type="api_token", target_id=token_id)
    _set_flash(request, "api.key_revoked")
    return _redirect("/api-access")

@router.post("/settings/debug-log/clear")
async def clear_debug_log(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    clear_debug_log_entries()
    _set_flash(request, "debug.cleared")
    return _redirect("/settings")


@router.post("/settings/interface")
async def update_interface_settings(
    request: Request,
    date_format: str = Form("de"),
    time_format: str = Form("24h"),
    timezone: str = Form("Europe/Berlin"),
    show_seconds: str | None = Form(None),
    compact_mode: str | None = Form(None),
    dashboard_refresh_seconds: int = Form(0),
):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_ui_preferences(
        SETTINGS.database_path,
        date_format=date_format,
        time_format=time_format,
        timezone=timezone,
        show_seconds=show_seconds == "on",
        compact_mode=compact_mode == "on",
        dashboard_refresh_seconds=dashboard_refresh_seconds,
    )
    audit.log_event(
        request,
        SETTINGS.database_path,
        "settings.interface_updated",
        detail={
            "date_format": date_format,
            "time_format": time_format,
            "timezone": timezone,
            "dashboard_refresh_seconds": dashboard_refresh_seconds,
        },
    )
    _set_flash(request, "settings.interface_saved")
    return _redirect("/settings")
