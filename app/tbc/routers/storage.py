"""Storage targets and the storage explorer.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

from fastapi import Form, Request
from fastapi.responses import HTMLResponse

from .. import audit, database
from ..maintenance import apply_cleanup, cleanup_preview, delete_recording_group, storage_overview
from fastapi import APIRouter

from ..main import (
    SETTINGS,
    _none_if_blank,
    _pop_flash,
    _redirect,
    _require_admin,
    _set_flash,
    _validated_storage_kind,
    templates,
)

router = APIRouter()


@router.get("/storage", response_class=HTMLResponse)
async def storage_targets(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "storage.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "storage_targets": database.list_storage_targets(SETTINGS.database_path),
            "defaults": {"local_path": SETTINGS.recordings_path},
            "flash": _pop_flash(request),
        },
    )

@router.post("/storage")
async def create_storage_target(
    request: Request,
    name: str = Form(...),
    kind: str = Form("local"),
    local_path: str = Form(""),
    s3_endpoint_url: str = Form(""),
    s3_region: str = Form(""),
    s3_bucket: str = Form(""),
    s3_prefix: str = Form(""),
    s3_access_key_id: str = Form(""),
    s3_secret_access_key: str = Form(""),
):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        database.create_storage_target(
            SETTINGS.database_path,
            name=name.strip(),
            kind=_validated_storage_kind(kind),
            local_path=_none_if_blank(local_path),
            s3_endpoint_url=_none_if_blank(s3_endpoint_url),
            s3_region=_none_if_blank(s3_region),
            s3_bucket=_none_if_blank(s3_bucket),
            s3_prefix=_none_if_blank(s3_prefix),
            s3_access_key_id=_none_if_blank(s3_access_key_id),
            s3_secret_access_key=_none_if_blank(s3_secret_access_key),
        )
        audit.log_event(request, SETTINGS.database_path, "storage.created", target_type="storage", detail={"name": name.strip(), "kind": kind})
        _set_flash(request, "storage.created")
    except Exception as exc:
        _set_flash(request, "storage.create_failed", {"error": exc}, "error")
    return _redirect("/storage")

@router.post("/storage/cleanup")
async def run_cleanup(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    deleted = apply_cleanup(SETTINGS.database_path)
    _set_flash(request, "recording.clips_deleted", {"count": deleted})
    return _redirect("/storage/explorer")

@router.post("/storage/{storage_id}")
async def update_storage_target(
    request: Request,
    storage_id: int,
    name: str = Form(...),
    kind: str = Form("local"),
    local_path: str = Form(""),
    s3_endpoint_url: str = Form(""),
    s3_region: str = Form(""),
    s3_bucket: str = Form(""),
    s3_prefix: str = Form(""),
    s3_access_key_id: str = Form(""),
    s3_secret_access_key: str = Form(""),
    retention_days: str = Form(""),
    retention_max_gb: str = Form(""),
):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_storage_target(
        SETTINGS.database_path,
        storage_id,
        name=name.strip(),
        kind=_validated_storage_kind(kind),
        local_path=_none_if_blank(local_path),
        s3_endpoint_url=_none_if_blank(s3_endpoint_url),
        s3_region=_none_if_blank(s3_region),
        s3_bucket=_none_if_blank(s3_bucket),
        s3_prefix=_none_if_blank(s3_prefix),
        s3_access_key_id=_none_if_blank(s3_access_key_id),
        s3_secret_access_key=_none_if_blank(s3_secret_access_key),
        retention_days=int(retention_days) if retention_days else None,
        retention_max_gb=float(retention_max_gb) if retention_max_gb else None,
    )
    audit.log_event(request, SETTINGS.database_path, "storage.updated", target_type="storage", target_id=storage_id, detail={"name": name.strip(), "kind": kind})
    _set_flash(request, "storage.updated")
    return _redirect("/storage")

@router.post("/storage/{storage_id}/delete")
async def remove_storage_target(request: Request, storage_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_storage_target(SETTINGS.database_path, storage_id)
    _set_flash(request, "storage.removed")
    return _redirect("/storage")

@router.get("/storage/explorer", response_class=HTMLResponse)
async def storage_explorer(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "storage_explorer.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "storage_targets": storage_overview(SETTINGS.database_path),
            "by_camera_event": database.list_recording_sizes_by_camera_event(SETTINGS.database_path),
            "cleanup_items": cleanup_preview(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )

@router.post("/storage/explorer/groups/delete")
async def delete_storage_explorer_group(
    request: Request,
    camera_id: int = Form(...),
    detection_key: str = Form(...),
    storage_id: str = Form(""),
):
    guard = _require_admin(request)
    if guard:
        return guard
    selected_storage_id = int(storage_id) if storage_id.strip() else None
    deleted = delete_recording_group(
        SETTINGS.database_path,
        camera_id=camera_id,
        detection_key=detection_key,
        storage_id=selected_storage_id,
    )
    audit.log_event(
        request,
        SETTINGS.database_path,
        "recording.group_deleted",
        target_type="camera",
        target_id=camera_id,
        detail={"detection_key": detection_key, "storage_id": selected_storage_id, "count": deleted},
    )
    _set_flash(request, "recording.clips_deleted", {"count": deleted})
    return _redirect("/storage/explorer")
