"""Camera/cloud/network plugin packages, plugin sources, design themes, and licenses.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from typing import Any

from fastapi import File, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from .. import database
from ..licenses import THIRD_PARTY_LICENSES, list_plugin_licenses
from ..camera_modules import (
    list_camera_module_registrations,
    reload_camera_modules,
)
from ..camera_modules.packages import (
    CameraPluginError,
    export_plugin_archive,
    install_plugin_archive,
    remove_external_plugin,
)
from ..cloud_modules import (
    list_cloud_module_registrations,
    reload_cloud_modules,
)
from ..cloud_modules.packages import (
    CloudPluginError,
    export_plugin_archive as export_cloud_plugin_archive,
    install_plugin_archive as install_cloud_plugin_archive,
    remove_external_plugin as remove_external_cloud_plugin,
)
from ..network_modules import (
    list_network_module_registrations,
    reload_network_modules,
)
from ..network_modules.packages import (
    NetworkPluginError,
    export_plugin_archive as export_network_plugin_archive,
    install_plugin_archive as install_network_plugin_archive,
    remove_external_plugin as remove_external_network_plugin,
)
from ..plugin_sources import (
    STANDARD_PLUGIN_SOURCES,
    PluginSourceError,
    get_standard_plugin_source,
    parse_github_repo_url,
)
from ..plugin_requirements import (
    MissingPluginRequirements,
    PluginRequirementsInstallError,
    install_requirements,
)
from ..plugin_testing import run_plugin_tests
from ..themes import UnknownThemeError, get_theme_registration, list_theme_registrations, reload_themes
from ..themes.packages import (
    ThemePackageError,
    export_theme_archive,
    install_theme_archive,
    remove_external_theme,
)
from fastapi import APIRouter

from ..main import (
    LOGGER,
    SETTINGS,
    _PLUGIN_TEMPLATE_BUILDERS,
    _find_registered_standard_source,
    _plugin_has_tests,
    _pop_flash,
    _redirect,
    _redirect_to_requirements_confirm,
    _refresh_camera,
    _require_admin,
    _safe_internal_path,
    _set_flash,
    _sync_plugin_source,
    templates,
)

router = APIRouter()


@router.get("/design/{theme_key}/static/{asset_path:path}", name="theme_asset")
async def theme_asset(theme_key: str, asset_path: str):
    try:
        registration = get_theme_registration(theme_key)
    except UnknownThemeError:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    relative = PurePosixPath(asset_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        return JSONResponse({"error": "invalid path"}, status_code=status.HTTP_400_BAD_REQUEST)
    file_path = registration.package.path / "static" / relative
    if not file_path.is_file():
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(file_path)

@router.get("/camera-modules", response_class=HTMLResponse)
async def camera_modules_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    registrations = list_camera_module_registrations()
    return templates.TemplateResponse(
        request,
        "camera_modules.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "registrations": registrations,
            "camera_counts": {
                registration.module.key: database.count_cameras_by_module(
                    SETTINGS.database_path,
                    registration.module.key,
                )
                for registration in registrations
            },
            "has_tests": {
                registration.module.key: _plugin_has_tests(registration.package)
                for registration in registrations
            },
            "flash": _pop_flash(request),
        },
    )

@router.post("/camera-modules/import")
async def import_camera_module(request: Request, plugin_file: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        archive = await plugin_file.read(10 * 1024 * 1024 + 1)
        package = install_plugin_archive(archive, SETTINGS.camera_modules_path)
        reload_camera_modules()
        _set_flash(request, "plugin.camera_installed", {"label": package.manifest.label})
    except MissingPluginRequirements as exc:
        return _redirect_to_requirements_confirm(exc, "/camera-modules")
    except (CameraPluginError, OSError) as exc:
        _set_flash(request, "plugin.camera_import_failed", {"error": exc}, "error")
    finally:
        await plugin_file.close()
    return _redirect("/camera-modules")

@router.get("/camera-modules/{module_key}/export")
async def export_camera_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_camera_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None or registration.package is None:
        return JSONResponse({"error": "Plugin cannot be exported"}, status_code=status.HTTP_404_NOT_FOUND)
    archive = export_plugin_archive(registration.package)
    filename = f"tbc-camera-plugin-{registration.module.key}-{registration.version}.zip"
    return Response(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.post("/camera-modules/{module_key}/delete")
async def delete_camera_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    camera_count = database.count_cameras_by_module(SETTINGS.database_path, module_key)
    if camera_count:
        _set_flash(request, "plugin.camera_still_in_use", {"count": camera_count}, "error")
        return _redirect("/camera-modules")
    try:
        remove_external_plugin(module_key, SETTINGS.camera_modules_path)
        reload_camera_modules()
        _set_flash(request, "plugin.camera_removed")
    except (CameraPluginError, OSError) as exc:
        _set_flash(request, "plugin.camera_remove_failed", {"error": exc}, "error")
    return _redirect("/camera-modules")

@router.post("/camera-modules/{module_key}/run-tests")
async def run_camera_module_tests(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_camera_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None or registration.package is None:
        _set_flash(request, "plugin.no_tests_available", None, "error")
        return _redirect("/camera-modules")
    result = await run_plugin_tests(registration.package.path, "camera")
    if not result.ran:
        _set_flash(request, "common.raw_message", {"message": result.summary}, "error")
    else:
        LOGGER.info("Plugin-Tests für %s: %s\n%s", module_key, result.summary, result.output)
        _set_flash(request, "plugin.test_result", {"module_key": module_key, "summary": result.summary})
    return _redirect("/camera-modules")

@router.get("/cloud-modules", response_class=HTMLResponse)
async def cloud_modules_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    registrations = list_cloud_module_registrations()
    return templates.TemplateResponse(
        request,
        "cloud_modules.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "registrations": registrations,
            "account_counts": {
                registration.module.key: database.count_cloud_accounts_by_module(
                    SETTINGS.database_path, registration.module.key
                )
                for registration in registrations
            },
            "has_tests": {
                registration.module.key: _plugin_has_tests(registration.package)
                for registration in registrations
            },
            "flash": _pop_flash(request),
        },
    )

@router.post("/cloud-modules/import")
async def import_cloud_module(request: Request, plugin_file: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        archive = await plugin_file.read(10 * 1024 * 1024 + 1)
        package = install_cloud_plugin_archive(archive, SETTINGS.cloud_modules_path)
        reload_cloud_modules()
        _set_flash(request, "plugin.cloud_installed", {"label": package.manifest.label})
    except MissingPluginRequirements as exc:
        return _redirect_to_requirements_confirm(exc, "/cloud-modules")
    except (CloudPluginError, OSError) as exc:
        _set_flash(request, "plugin.cloud_import_failed", {"error": exc}, "error")
    finally:
        await plugin_file.close()
    return _redirect("/cloud-modules")

@router.get("/cloud-modules/{module_key}/export")
async def export_cloud_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_cloud_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None:
        return JSONResponse({"error": "Plugin cannot be exported"}, status_code=status.HTTP_404_NOT_FOUND)
    archive = export_cloud_plugin_archive(registration.package)
    filename = f"tbc-cloud-plugin-{registration.module.key}-{registration.version}.zip"
    return Response(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.post("/cloud-modules/{module_key}/delete")
async def delete_cloud_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    account_count = database.count_cloud_accounts_by_module(SETTINGS.database_path, module_key)
    if account_count:
        _set_flash(request, "plugin.cloud_still_in_use", {"count": account_count}, "error")
        return _redirect("/cloud-modules")
    try:
        remove_external_cloud_plugin(module_key, SETTINGS.cloud_modules_path)
        reload_cloud_modules()
        _set_flash(request, "plugin.cloud_removed")
    except (CloudPluginError, OSError) as exc:
        _set_flash(request, "plugin.cloud_remove_failed", {"error": exc}, "error")
    return _redirect("/cloud-modules")

@router.post("/cloud-modules/{module_key}/run-tests")
async def run_cloud_module_tests(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_cloud_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None:
        _set_flash(request, "plugin.no_tests_available", None, "error")
        return _redirect("/cloud-modules")
    result = await run_plugin_tests(registration.package.path, "cloud")
    if not result.ran:
        _set_flash(request, "common.raw_message", {"message": result.summary}, "error")
    else:
        LOGGER.info("Plugin-Tests für %s: %s\n%s", module_key, result.summary, result.output)
        _set_flash(request, "plugin.test_result", {"module_key": module_key, "summary": result.summary})
    return _redirect("/cloud-modules")

@router.get("/network-modules", response_class=HTMLResponse)
async def network_modules_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    registrations = list_network_module_registrations()
    return templates.TemplateResponse(
        request,
        "network_modules.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "registrations": registrations,
            "account_counts": {
                registration.module.key: database.count_network_accounts_by_module(
                    SETTINGS.database_path, registration.module.key
                )
                for registration in registrations
            },
            "has_tests": {
                registration.module.key: _plugin_has_tests(registration.package)
                for registration in registrations
            },
            "flash": _pop_flash(request),
        },
    )

@router.post("/network-modules/import")
async def import_network_module(request: Request, plugin_file: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        archive = await plugin_file.read(10 * 1024 * 1024 + 1)
        package = install_network_plugin_archive(archive, SETTINGS.network_modules_path)
        reload_network_modules()
        _set_flash(request, "plugin.network_installed", {"label": package.manifest.label})
    except MissingPluginRequirements as exc:
        return _redirect_to_requirements_confirm(exc, "/network-modules")
    except (NetworkPluginError, OSError) as exc:
        _set_flash(request, "plugin.network_import_failed", {"error": exc}, "error")
    finally:
        await plugin_file.close()
    return _redirect("/network-modules")

@router.get("/network-modules/{module_key}/export")
async def export_network_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_network_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None:
        return JSONResponse({"error": "Plugin cannot be exported"}, status_code=status.HTTP_404_NOT_FOUND)
    archive = export_network_plugin_archive(registration.package)
    filename = f"tbc-network-plugin-{registration.module.key}-{registration.version}.zip"
    return Response(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.post("/network-modules/{module_key}/delete")
async def delete_network_module(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    account_count = database.count_network_accounts_by_module(SETTINGS.database_path, module_key)
    if account_count:
        _set_flash(request, "plugin.network_still_in_use", {"count": account_count}, "error")
        return _redirect("/network-modules")
    try:
        remove_external_network_plugin(module_key, SETTINGS.network_modules_path)
        reload_network_modules()
        _set_flash(request, "plugin.network_removed")
    except (NetworkPluginError, OSError) as exc:
        _set_flash(request, "plugin.network_remove_failed", {"error": exc}, "error")
    return _redirect("/network-modules")

@router.post("/network-modules/{module_key}/run-tests")
async def run_network_module_tests(request: Request, module_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    registration = next(
        (item for item in list_network_module_registrations() if item.module.key == module_key),
        None,
    )
    if registration is None:
        _set_flash(request, "plugin.no_tests_available", None, "error")
        return _redirect("/network-modules")
    result = await run_plugin_tests(registration.package.path, "network")
    if not result.ran:
        _set_flash(request, "common.raw_message", {"message": result.summary}, "error")
    else:
        LOGGER.info("Plugin-Tests für %s: %s\n%s", module_key, result.summary, result.output)
        _set_flash(request, "plugin.test_result", {"module_key": module_key, "summary": result.summary})
    return _redirect("/network-modules")

@router.get("/design", response_class=HTMLResponse)
async def design_themes_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    active_theme_key = database.get_active_theme_key(SETTINGS.database_path)
    return templates.TemplateResponse(
        request,
        "design.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "registrations": list_theme_registrations(),
            "active_theme_key": active_theme_key,
            "flash": _pop_flash(request),
        },
    )

@router.post("/design/activate")
async def activate_design_theme(request: Request, theme_key: str = Form(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        get_theme_registration(theme_key)
    except UnknownThemeError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/design")
    database.set_active_theme_key(SETTINGS.database_path, theme_key.strip().lower())
    _set_flash(request, "design.activated")
    return _redirect("/design")

@router.post("/design/import")
async def import_design_theme(request: Request, theme_file: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        archive = await theme_file.read(5 * 1024 * 1024 + 1)
        package = install_theme_archive(archive, SETTINGS.theme_modules_path)
        reload_themes()
        _set_flash(request, "design.installed", {"label": package.manifest.label})
    except (ThemePackageError, OSError) as exc:
        _set_flash(request, "design.import_failed", {"error": exc}, "error")
    finally:
        await theme_file.close()
    return _redirect("/design")

@router.get("/design/{theme_key}/export")
async def export_design_theme(request: Request, theme_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        registration = get_theme_registration(theme_key)
    except UnknownThemeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)
    archive = export_theme_archive(registration.package)
    filename = f"tbc-design-{registration.manifest.key}-{registration.manifest.version}.zip"
    return Response(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.post("/design/{theme_key}/delete")
async def delete_design_theme(request: Request, theme_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    active_theme_key = database.get_active_theme_key(SETTINGS.database_path)
    if theme_key.strip().lower() == active_theme_key:
        _set_flash(request, "design.cannot_remove_active", None, "error")
        return _redirect("/design")
    try:
        remove_external_theme(theme_key, SETTINGS.theme_modules_path)
        reload_themes()
        _set_flash(request, "design.removed")
    except (ThemePackageError, OSError) as exc:
        _set_flash(request, "design.remove_failed", {"error": exc}, "error")
    return _redirect("/design")

@router.get("/plugin-sources/template/{plugin_kind}")
async def download_plugin_template(request: Request, plugin_kind: str):
    guard = _require_admin(request)
    if guard:
        return guard
    entry = _PLUGIN_TEMPLATE_BUILDERS.get(plugin_kind)
    if entry is None:
        return JSONResponse({"error": "Unknown plugin type"}, status_code=status.HTTP_404_NOT_FOUND)
    builder, name = entry
    return Response(
        builder(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="tbc-plugin-vorlage-{name}.zip"'},
    )

@router.get("/plugin-sources", response_class=HTMLResponse)
async def plugin_sources_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    sources = database.list_plugin_sources(SETTINGS.database_path)
    return templates.TemplateResponse(
        request,
        "plugin_sources.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "sources": sources,
            "standard_sources": [
                {
                    "source": standard_source,
                    "registered_source": _find_registered_standard_source(standard_source, sources),
                }
                for standard_source in STANDARD_PLUGIN_SOURCES
            ],
            "flash": _pop_flash(request),
        },
    )

@router.post("/plugin-sources")
async def create_plugin_source_route(
    request: Request,
    plugin_kind: str = Form(...),
    label: str = Form(""),
    repo_url: str = Form(...),
    ref: str = Form("main"),
    subdirectory: str = Form(""),
):
    guard = _require_admin(request)
    if guard:
        return guard
    if plugin_kind not in ("camera", "cloud", "network", "design"):
        _set_flash(request, "plugin.invalid_kind", None, "error")
        return _redirect("/plugin-sources")
    try:
        parse_github_repo_url(repo_url)
    except PluginSourceError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect("/plugin-sources")
    database.create_plugin_source(
        SETTINGS.database_path,
        plugin_kind=plugin_kind,
        label=label.strip() or repo_url.strip(),
        repo_url=repo_url.strip(),
        ref=ref.strip() or "main",
        subdirectory=subdirectory.strip(),
    )
    _set_flash(request, "plugin_source.added")
    return _redirect("/plugin-sources")

@router.post("/plugin-sources/standard/{source_key}/install")
async def install_standard_plugin_source_route(request: Request, source_key: str):
    guard = _require_admin(request)
    if guard:
        return guard
    standard_source = get_standard_plugin_source(source_key)
    if standard_source is None:
        _set_flash(request, "plugin_source.standard_not_found", None, "error")
        return _redirect("/plugin-sources")
    registered_source = _find_registered_standard_source(
        standard_source, database.list_plugin_sources(SETTINGS.database_path)
    )
    if registered_source is None:
        source_id = database.create_plugin_source(
            SETTINGS.database_path,
            plugin_kind=standard_source.plugin_kind,
            label=standard_source.label,
            repo_url=standard_source.repo_url,
            ref=standard_source.ref,
            subdirectory=standard_source.subdirectory,
        )
    else:
        source_id = int(registered_source["id"])
    return await _sync_plugin_source(request, source_id, "/plugin-sources")

@router.post("/plugin-sources/{source_id}/sync")
async def sync_plugin_source_route(request: Request, source_id: int, return_to: str = Form("/plugin-sources")):
    guard = _require_admin(request)
    if guard:
        return guard
    redirect_target = return_to if return_to in ("/plugin-sources", "/updates") else "/plugin-sources"
    return await _sync_plugin_source(request, source_id, redirect_target)

@router.post("/plugin-sources/{source_id}/delete")
async def delete_plugin_source_route(request: Request, source_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_plugin_source(SETTINGS.database_path, source_id)
    _set_flash(request, "plugin_source.removed")
    return _redirect("/plugin-sources")

@router.get("/plugin-requirements/confirm", response_class=HTMLResponse)
async def plugin_requirements_confirm_page(
    request: Request,
    requirements: list[str] = Query(...),
    retry_url: str = Query("/plugin-sources"),
    label: str = Query(""),
    source_id: int | None = Query(None),
    plugin_kind: str = Query(""),
    module_key: str = Query(""),
):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "plugin_requirements_confirm.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "requirements": requirements,
            "retry_url": _safe_internal_path(retry_url, "/plugin-sources"),
            "label": label,
            "source_id": source_id,
            "plugin_kind": plugin_kind,
            "module_key": module_key,
            "flash": _pop_flash(request),
        },
    )

@router.post("/plugin-requirements/install")
async def install_plugin_requirements_route(
    request: Request,
    requirements: list[str] = Form(...),
    retry_url: str = Form("/plugin-sources"),
    source_id: int | None = Form(None),
    plugin_kind: str = Form(""),
    module_key: str = Form(""),
):
    guard = _require_admin(request)
    if guard:
        return guard
    safe_retry_url = _safe_internal_path(retry_url, "/plugin-sources")
    try:
        await install_requirements(tuple(requirements))
    except PluginRequirementsInstallError as exc:
        _set_flash(request, "common.raw_message", {"message": str(exc)}, "error")
        return _redirect(safe_retry_url)
    if plugin_kind == "camera" and module_key:
        # The packages just installed may be exactly what an already-
        # configured camera on this module was missing - refresh it now
        # instead of leaving its detail page showing a stale "library not
        # installed" probe result until the next background poll cycle or a
        # manual "Refresh" click.
        for camera_id in database.list_camera_ids_by_module(SETTINGS.database_path, module_key):
            asyncio.create_task(_refresh_camera(camera_id))
    if source_id is not None:
        # Came from a GitHub-sync attempt, not a ZIP upload - we know exactly
        # which source to retry, so do it now instead of making the admin
        # click "Update now"/"Install directly" again (each manual retry is
        # another GitHub API call against the unauthenticated rate limit).
        return await _sync_plugin_source(request, source_id, safe_retry_url)
    _set_flash(request, "plugin.requirements_installed", {"count": len(requirements)})
    return _redirect(safe_retry_url)

@router.get("/updates", response_class=HTMLResponse)
async def plugin_updates_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    pending_sources = [
        source
        for source in database.list_plugin_sources(SETTINGS.database_path)
        if source.get("update_available")
    ]
    return templates.TemplateResponse(
        request,
        "plugin_updates.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "sources": pending_sources,
            "flash": _pop_flash(request),
        },
    )

@router.get("/license", response_class=HTMLResponse)
async def license_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    categories: list[dict[str, Any]] = []
    for entry in THIRD_PARTY_LICENSES:
        category = next((c for c in categories if c["name"] == entry["category"]), None)
        if category is None:
            category = {"name": entry["category"], "tools": []}
            categories.append(category)
        category["tools"].append(entry)
    return templates.TemplateResponse(
        request,
        "license.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "categories": categories,
            "plugin_licenses": list_plugin_licenses(),
            "flash": _pop_flash(request),
        },
    )
