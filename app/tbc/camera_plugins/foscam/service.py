from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from tbc_camera_api import CameraSnapshot
from tbc_camera_api import onvif as _onvif
from tbc_camera_api import streams as _streams
from .catalog import catalog_rows

probe_onvif = _onvif.probe_onvif
rtsp_uri_with_credentials = _streams.rtsp_uri_with_credentials


async def probe_camera(camera: dict[str, Any]) -> CameraSnapshot:
    onvif_probe = await asyncio.to_thread(
        probe_onvif,
        host=camera["host"],
        port=int(camera.get("onvif_port") or 888),
        username=camera["username"],
        password=camera["password"],
    )
    stream_uri = (
        rtsp_uri_with_credentials(onvif_probe.stream_uris[0], camera["username"], camera["password"])
        if onvif_probe.stream_uris
        else foscam_rtsp_uri(camera, stream="videoMain")
    )
    messages = [onvif_probe.message]
    if not onvif_probe.success:
        messages.append("RTSP-Stream wurde nach dem Foscam-Standardpfad /videoMain konfiguriert")

    return CameraSnapshot(
        status="ok" if onvif_probe.success else "warn",
        message=" | ".join(message for message in messages if message),
        manufacturer=onvif_probe.manufacturer or "Foscam",
        model=onvif_probe.model,
        firmware=onvif_probe.firmware,
        serial=onvif_probe.serial,
        stream_uri=stream_uri,
        detections=catalog_rows(onvif_probe.event_detection_keys),
    )


def foscam_rtsp_uri(camera: dict[str, Any], *, stream: str = "videoMain") -> str:
    username = quote(str(camera["username"]), safe="")
    password = quote(str(camera["password"]), safe="")
    host = str(camera["host"]).strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = int(camera.get("rtsp_port") or 554)
    path = "videoSub" if stream == "videoSub" else "videoMain"
    return f"rtsp://{username}:{password}@{host}:{port}/{path}"
