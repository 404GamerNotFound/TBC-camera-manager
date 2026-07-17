from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP, Image
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from . import database
from .api_common import api_auth_error, camera_public_dict, recording_public_dict, storage_public_dict
from .health import current_system_usage
from .snapshots import DashboardSnapshotManager

# MCP shares TBC's external API auth (see app/tbc/api_common.py, docs/mcp.md) - there is no
# separate MCP-specific key. DNS-rebinding protection is disabled deliberately: TBC is reached
# over arbitrary LAN IPs/domains, and the API key is the real access boundary here, not the
# Host header (see docs/mcp.md).
_TRANSPORT_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)


class _McpAuthMiddleware:
    """Gates the mounted MCP app behind the same api_config used by /api/v1/...

    A plain ASGI wrapper rather than FastMCP's own OAuth `auth` support, which is built for
    full OAuth authorization-code flows - overkill for a single shared bearer API key.
    """

    def __init__(self, app: ASGIApp, database_path: str) -> None:
        self.app = app
        self.database_path = database_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        auth_header = headers.get(b"authorization", b"").decode("latin-1") or None
        api_key_header = headers.get(b"x-api-key", b"").decode("latin-1") or None
        config = database.get_api_config(self.database_path)
        error = api_auth_error(
            config,
            auth_header,
            api_key_header,
            find_token=lambda prefix: database.find_active_api_token_by_prefix(self.database_path, prefix),
            on_success=lambda token: database.touch_api_token_last_used(self.database_path, int(token["id"])),
        )
        if error:
            code, message = error
            await JSONResponse({"error": message}, status_code=code)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def build_mcp_app(
    *,
    database_path: str,
    app_name: str,
    app_version: str,
    app_update_state: dict[str, Any],
    snapshot_manager: DashboardSnapshotManager,
    snapshot_semaphore: asyncio.Semaphore,
    stream_uri_for: Callable[[dict[str, Any]], str | None],
) -> tuple[ASGIApp, AbstractAsyncContextManager[None]]:
    """Build the mountable MCP Streamable-HTTP app plus its session-manager lifespan.

    The caller (main.py) must enter/exit the returned context manager around the app's own
    startup/shutdown - see docs/mcp.md and the plan notes for why a plain .mount() is not
    enough (the StreamableHTTPSessionManager needs its own running task group).
    """
    mcp = FastMCP(
        "tbc-camera-manager",
        instructions=(
            f"Read-only access to {app_name}, a self-hosted camera/NVR manager. "
            "Use these tools to answer questions about cameras, recordings, detections, "
            "storage, and system health."
        ),
        stateless_http=True,
        transport_security=_TRANSPORT_SECURITY,
    )

    @mcp.tool()
    async def list_cameras() -> list[dict[str, Any]]:
        """List all configured cameras with their capabilities and current status."""
        cameras = await asyncio.to_thread(database.list_cameras, database_path)
        return [camera_public_dict(camera) for camera in cameras]

    @mcp.tool()
    async def get_camera(camera_id: int) -> dict[str, Any]:
        """Get details for a single camera by its ID."""
        camera = await asyncio.to_thread(database.get_camera, database_path, camera_id)
        if not camera:
            raise ToolError(f"Camera {camera_id} not found")
        return camera_public_dict(camera)

    @mcp.tool()
    async def get_camera_detections(camera_id: int) -> dict[str, Any]:
        """Get the current detection state (motion, person, vehicle, ...) for a camera."""
        camera = await asyncio.to_thread(database.get_camera, database_path, camera_id)
        if not camera:
            raise ToolError(f"Camera {camera_id} not found")
        detections = await asyncio.to_thread(database.list_detections, database_path, camera_id)
        return {"camera_id": camera_id, "detections": detections}

    @mcp.tool()
    async def get_camera_snapshot(camera_id: int) -> Image:
        """Get the current live snapshot image for a camera."""
        camera = await asyncio.to_thread(database.get_camera, database_path, camera_id)
        if not camera:
            raise ToolError(f"Camera {camera_id} not found")
        stream_uri = stream_uri_for(camera)
        if not stream_uri:
            raise ToolError(f"Camera {camera_id} has no stream configured")
        async with snapshot_semaphore:
            snapshot_path = await asyncio.to_thread(snapshot_manager.refresh_if_due, camera_id, stream_uri)
        if snapshot_path is None or not snapshot_path.exists():
            raise ToolError("Snapshot not available")
        return Image(data=snapshot_path.read_bytes(), format="jpeg")

    @mcp.tool()
    async def list_recordings(
        camera_id: int | None = None,
        detection_key: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List event recordings, optionally filtered by camera, detection type, or date
        range (ISO date/datetime strings). Excludes continuous 24/7 footage."""
        recordings = await asyncio.to_thread(
            database.list_recordings,
            database_path,
            camera_id=camera_id,
            detection_key=detection_key,
            date_from=date_from,
            date_to=date_to,
            role="admin",
            limit=max(1, min(200, limit)),
        )
        return [recording_public_dict(recording) for recording in recordings]

    @mcp.tool()
    async def get_recording(recording_id: int) -> dict[str, Any]:
        """Get metadata for a single recording by its ID."""
        recording = await asyncio.to_thread(database.get_recording, database_path, recording_id)
        if not recording:
            raise ToolError(f"Recording {recording_id} not found")
        return recording_public_dict(recording)

    @mcp.tool()
    async def get_recording_snapshot(recording_id: int) -> Image:
        """Get the event thumbnail image for a recording, if one was captured locally."""
        recording = await asyncio.to_thread(database.get_recording, database_path, recording_id)
        if not recording:
            raise ToolError(f"Recording {recording_id} not found")
        snapshot_path = recording.get("snapshot_path")
        if not snapshot_path:
            raise ToolError("No local snapshot available for this recording")
        path = await asyncio.to_thread(_read_snapshot_bytes, snapshot_path)
        if path is None:
            raise ToolError("Snapshot file not found on disk")
        return Image(data=path, format="jpeg")

    @mcp.tool()
    async def get_activity(day: str | None = None) -> dict[str, Any]:
        """Get event recordings across all cameras for a given day (ISO date, default today)."""
        selected_day = _parse_day(day)
        cameras = await asyncio.to_thread(database.list_cameras, database_path)
        camera_ids = [int(camera["id"]) for camera in cameras]
        start_at = f"{selected_day.isoformat()}T00:00:00"
        end_at = f"{(selected_day + timedelta(days=1)).isoformat()}T00:00:00"
        rows = await asyncio.to_thread(
            database.list_event_recordings_for_cameras_range,
            database_path,
            camera_ids=camera_ids,
            start_at=start_at,
            end_at=end_at,
        )
        events_by_camera: dict[int, list[dict[str, Any]]] = {camera_id: [] for camera_id in camera_ids}
        for row in rows:
            events_by_camera.setdefault(int(row["camera_id"]), []).append(row)
        return {
            "day": selected_day.isoformat(),
            "cameras": [
                {
                    "id": int(camera["id"]),
                    "name": camera["name"],
                    "events": [recording_public_dict(row) for row in events_by_camera.get(int(camera["id"]), [])],
                }
                for camera in cameras
            ],
        }

    @mcp.tool()
    async def get_storage() -> list[dict[str, Any]]:
        """List configured storage targets (local paths and S3-compatible buckets)."""
        targets = await asyncio.to_thread(database.list_storage_targets, database_path)
        return [storage_public_dict(target) for target in targets]

    @mcp.tool()
    async def get_health() -> dict[str, Any]:
        """Get system resource usage and health status/events for cameras, storage, and MQTT."""
        system_usage = await asyncio.to_thread(current_system_usage)
        return {
            "system_usage": system_usage,
            "items": await asyncio.to_thread(database.list_health_status, database_path),
            "events": await asyncio.to_thread(database.list_health_events, database_path),
        }

    @mcp.tool()
    async def get_status() -> dict[str, Any]:
        """Get the app name, version, update availability, and camera count."""
        cameras = await asyncio.to_thread(database.list_cameras, database_path)
        return {
            "app_name": app_name,
            "app_version": app_version,
            "update_available": app_update_state["update_available"],
            "latest_version": app_update_state["latest_version"],
            "camera_count": len(cameras),
        }

    mcp_app = mcp.streamable_http_app()
    wrapped = _McpAuthMiddleware(mcp_app, database_path)
    return wrapped, mcp.session_manager.run()


def _parse_day(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError:
        return date.today()


def _read_snapshot_bytes(path: str) -> bytes | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    return file_path.read_bytes()
