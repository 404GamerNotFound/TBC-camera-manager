from __future__ import annotations

from typing import Any

from fastapi import Request

from . import database


def log_event(
    request: Request,
    database_path: str,
    action: str,
    *,
    target_type: str | None = None,
    target_id: Any = None,
    detail: dict[str, Any] | None = None,
    username_override: str | None = None,
) -> None:
    """Record a security-relevant audit event tied to the current request's session."""
    user_id = request.session.get("user_id")
    username = username_override or request.session.get("username") or "anonymous"
    ip_address = request.client.host if request.client else None
    database.record_audit_event(
        database_path,
        user_id=int(user_id) if user_id else None,
        username=username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=ip_address,
    )
