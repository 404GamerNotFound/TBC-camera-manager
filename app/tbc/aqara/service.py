from __future__ import annotations

import asyncio
from typing import Any

from ..camera_modules.base import CameraSnapshot
from ..camera_modules.onvif import probe_onvif
from ..camera_modules.streams import build_rtsp_uri, probe_rtsp_stream, rtsp_uri_with_credentials
from .catalog import catalog_rows


async def probe_camera(camera: dict[str, Any]) -> CameraSnapshot:
    fallback_uri = build_rtsp_uri(
        host=camera["host"],
        port=int(camera.get("rtsp_port") or 8554),
        path="ch1",
        username=camera["username"],
        password=camera["password"],
    )
    onvif_probe, fallback_result = await asyncio.gather(
        asyncio.to_thread(
            probe_onvif,
            host=camera["host"],
            port=int(camera.get("onvif_port") or 5000),
            username=camera["username"],
            password=camera["password"],
        ),
        asyncio.to_thread(probe_rtsp_stream, fallback_uri),
    )
    discovered_uri = (
        rtsp_uri_with_credentials(onvif_probe.stream_uris[0], camera["username"], camera["password"])
        if onvif_probe.stream_uris
        else None
    )
    fallback_status, fallback_message = fallback_result
    stream_uri = discovered_uri or (fallback_uri if fallback_status in {"ok", "warning"} else None)

    messages: list[str] = []
    if onvif_probe.success:
        messages.append(onvif_probe.message)
    if discovered_uri:
        messages.append("Aqara-Stream wurde über ONVIF ermittelt")
    elif fallback_status == "ok":
        messages.append("Aqara-RTSP-Stream /ch1 ist erreichbar")
        messages.append("G410: RTSP benötigt kabelgebundene Stromversorgung; G4 unterstützt kein RTSP")
    elif fallback_status == "warning":
        messages.append(fallback_message)
        messages.append("Aqara-RTSP-Fallback /ch1 wurde konfiguriert")
    else:
        messages.append("Kein lokaler Aqara-Stream gefunden")
        messages.append("G4 unterstützt kein RTSP; G410 benötigt Kabelstrom und aktivierte RTSP-LAN-Vorschau")

    if discovered_uri or fallback_status == "ok":
        status = "ok"
    elif onvif_probe.success or fallback_status == "warning":
        status = "warn"
    else:
        status = "error"
    return CameraSnapshot(
        status=status,
        message=" | ".join(messages),
        manufacturer=onvif_probe.manufacturer or "Aqara",
        model=onvif_probe.model,
        firmware=onvif_probe.firmware,
        serial=onvif_probe.serial,
        stream_uri=stream_uri,
        detections=catalog_rows(onvif_probe.event_detection_keys),
    )
