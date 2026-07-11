from __future__ import annotations

import asyncio
from typing import Any

from ..camera_modules.base import CameraSnapshot
from ..camera_modules.onvif import probe_onvif
from ..camera_modules.streams import rtsp_uri_with_credentials
from .catalog import catalog_rows


async def probe_camera(camera: dict[str, Any]) -> CameraSnapshot:
    onvif_probe = await asyncio.to_thread(
        probe_onvif,
        host=camera["host"],
        port=int(camera.get("onvif_port") or 80),
        username=camera["username"],
        password=camera["password"],
    )
    stream_uri = (
        rtsp_uri_with_credentials(onvif_probe.stream_uris[0], camera["username"], camera["password"])
        if onvif_probe.stream_uris
        else None
    )
    if not onvif_probe.success:
        status = "error"
    elif stream_uri:
        status = "ok"
    else:
        status = "warn"
    messages = [onvif_probe.message]
    if onvif_probe.success and not stream_uri:
        messages.append("ONVIF liefert keinen RTSP-Medienstream")
    return CameraSnapshot(
        status=status,
        message=" | ".join(message for message in messages if message),
        manufacturer=onvif_probe.manufacturer,
        model=onvif_probe.model,
        firmware=onvif_probe.firmware,
        serial=onvif_probe.serial,
        stream_uri=stream_uri,
        detections=catalog_rows(onvif_probe.event_detection_keys),
    )
