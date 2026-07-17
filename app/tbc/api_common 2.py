from __future__ import annotations

from typing import Any

from .camera_modules import get_camera_module
from .camera_modules.registry import UnknownCameraModuleError
from .live import redact_rtsp_credentials
from .security import verify_api_key

__all__ = [
    "api_auth_error",
    "camera_public_dict",
    "recording_public_dict",
    "storage_public_dict",
]


def api_auth_error(
    config: dict[str, Any], auth_header: str | None, api_key_header: str | None
) -> tuple[int, str] | None:
    if not config["enabled"]:
        return (404, "API ist deaktiviert")
    if not config["require_api_key"]:
        return None
    token = ""
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    token = token or (api_key_header or "").strip()
    if not token or not config.get("api_key_hash") or not verify_api_key(token, config["api_key_hash"]):
        return (401, "invalid or missing API key")
    return None


def camera_public_dict(camera: dict[str, Any]) -> dict[str, Any]:
    try:
        camera_module = get_camera_module(camera.get("module_key"))
    except UnknownCameraModuleError:
        camera_module = None
    return {
        "id": int(camera["id"]),
        "name": camera["name"],
        "module_key": camera.get("module_key"),
        "module_label": camera_module.label if camera_module else None,
        "capabilities": sorted(c.value for c in camera_module.capabilities) if camera_module else [],
        "enabled": bool(camera.get("enabled")),
        "manufacturer": camera.get("manufacturer"),
        "model": camera.get("model"),
        "firmware": camera.get("firmware"),
        "status": camera.get("last_probe_status"),
        "status_message": camera.get("last_probe_message"),
        "stream_uri": redact_rtsp_credentials(camera["stream_uri"]) if camera.get("stream_uri") else None,
        "recording_enabled": bool(camera.get("recording_enabled")),
        "continuous_recording_enabled": bool(camera.get("continuous_recording_enabled")),
        "snapshot_enabled": bool(camera.get("snapshot_enabled")),
        "detection_count": camera.get("detection_count"),
        "supported_count": camera.get("supported_count"),
        "active_count": camera.get("active_count"),
        "snapshot_url": f"/api/v1/cameras/{camera['id']}/snapshot",
        "created_at": camera.get("created_at"),
        "updated_at": camera.get("updated_at"),
    }


def recording_public_dict(recording: dict[str, Any]) -> dict[str, Any]:
    has_snapshot = bool(recording.get("snapshot_path") or recording.get("snapshot_remote_key"))
    return {
        "id": int(recording["id"]),
        "camera_id": int(recording["camera_id"]),
        "camera_name": recording.get("camera_name"),
        "detection_key": recording.get("detection_key"),
        "label": recording.get("event_label"),
        "status": recording.get("status"),
        "started_at": recording.get("started_at"),
        "ended_at": recording.get("ended_at"),
        "duration_seconds": recording.get("duration_seconds"),
        "size_bytes": recording.get("size_bytes"),
        "mime_type": recording.get("mime_type"),
        "media_url": f"/api/v1/recordings/{recording['id']}/media",
        "snapshot_url": f"/api/v1/recordings/{recording['id']}/snapshot" if has_snapshot else None,
    }


def storage_public_dict(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(target["id"]),
        "name": target.get("name"),
        "kind": target.get("kind"),
        "local_path": target.get("local_path"),
        "s3_bucket": target.get("s3_bucket"),
        "s3_region": target.get("s3_region"),
        "retention_days": target.get("retention_days"),
        "retention_max_gb": target.get("retention_max_gb"),
    }
