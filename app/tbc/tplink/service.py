from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from ..camera_modules.base import CameraSnapshot
from ..camera_modules.onvif import probe_onvif
from .catalog import catalog_rows


async def probe_camera(camera: dict[str, Any]) -> CameraSnapshot:
    onvif_probe = await asyncio.to_thread(
        probe_onvif,
        host=camera["host"],
        port=int(camera.get("onvif_port") or 2020),
        username=camera["username"],
        password=camera["password"],
    )
    stream_uri = tapo_rtsp_uri(camera, stream="stream1")
    messages = [onvif_probe.message]
    if not onvif_probe.success:
        messages.append("RTSP-Stream wurde nach dem TP-Link/Tapo-Standard konfiguriert")

    return CameraSnapshot(
        status="ok" if onvif_probe.success else "warn",
        message=" | ".join(message for message in messages if message),
        manufacturer=onvif_probe.manufacturer or "TP-Link",
        model=onvif_probe.model,
        firmware=onvif_probe.firmware,
        serial=onvif_probe.serial,
        stream_uri=stream_uri,
        detections=catalog_rows(onvif_probe.event_detection_keys),
    )


def tapo_rtsp_uri(camera: dict[str, Any], *, stream: str = "stream1") -> str:
    username = quote(str(camera["username"]), safe="")
    password = quote(str(camera["password"]), safe="")
    host = str(camera["host"]).strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = int(camera.get("rtsp_port") or 554)
    stream_name = "stream2" if stream == "stream2" else "stream1"
    return f"rtsp://{username}:{password}@{host}:{port}/{stream_name}"
