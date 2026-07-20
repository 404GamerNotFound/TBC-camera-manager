"""In-app documentation viewer and the health dashboard page.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import asyncio

from fastapi import Request
from fastapi.responses import HTMLResponse

from .. import database
from ..health import current_system_usage
from fastapi import APIRouter

from ..main import (
    SETTINGS,
    _documentation_response,
    _pop_flash,
    _require_admin,
    templates,
)

router = APIRouter()


@router.get("/docs", response_class=HTMLResponse)
async def documentation_index(request: Request):
    return _documentation_response(request, "README.md")

@router.get("/docs/{document_name}", response_class=HTMLResponse)
async def documentation_page(request: Request, document_name: str):
    return _documentation_response(request, document_name)

@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    system_usage = await asyncio.to_thread(current_system_usage)
    return templates.TemplateResponse(
        request,
        "health.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "system_usage": system_usage,
            "items": database.list_health_status(SETTINGS.database_path),
            "events": database.list_health_events(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )
