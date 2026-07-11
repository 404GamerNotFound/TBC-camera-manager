from __future__ import annotations

import asyncio
from typing import Any

from ...camera_modules.base import CameraSnapshot
from ...camera_modules.onvif import probe_onvif
from ...camera_modules.streams import build_rtsp_uri, probe_rtsp_stream, rtsp_uri_with_credentials
from .catalog import catalog_rows


async def probe_camera(camera: dict[str, Any]) -> CameraSnapshot:
    fallback_uris = [
        build_rtsp_uri(
            host=camera["host"],
            port=int(camera.get("rtsp_port") or 8554),
            path=f"ch{channel}",
            username=camera["username"],
            password=camera["password"],
        )
        for channel in (1, 2, 3)
    ]
    fallback_uri = fallback_uris[0]
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
    discovered_uris = [
        rtsp_uri_with_credentials(uri, camera["username"], camera["password"])
        for uri in onvif_probe.stream_uris
    ]
    discovered_uri = discovered_uris[0] if discovered_uris else None
    fallback_status, fallback_message = fallback_result
    stream_uri = discovered_uri or (fallback_uri if fallback_status in {"ok", "warning"} else None)

    messages: list[str] = []
    if onvif_probe.success:
        messages.append(onvif_probe.message)
    if discovered_uri:
        messages.append("Aqara-Stream wurde über ONVIF ermittelt")
    elif fallback_status == "ok":
        messages.append("Aqara-RTSP-Stream /ch1 ist erreichbar")
        messages.append("Aqara-LAN-Streaming ist aktiv")
    elif fallback_status == "warning":
        messages.append(fallback_message)
        messages.append("Aqara-RTSP-Fallback /ch1 wurde konfiguriert")
    else:
        messages.append("Kein lokaler Aqara-Stream gefunden")
        if _is_authentication_error(fallback_message):
            messages.append("RTSP-Anmeldung abgelehnt: Die von Aqara erzeugten LAN-Zugangsdaten in TBC eintragen")
        else:
            messages.append(
                "G400: In Aqara Home unter Weitere Einstellungen die RTSP-LAN-Vorschau aktivieren; "
                "dadurch wird auch ONVIF freigeschaltet"
            )
            messages.append("Die dort angezeigten RTSP-LAN-Zugangsdaten in TBC verwenden")

    if discovered_uri or fallback_status == "ok":
        status = "ok"
    elif onvif_probe.success or fallback_status == "warning":
        status = "warn"
    else:
        status = "error"
    channel_uris = discovered_uris or (fallback_uris if fallback_status in {"ok", "warning"} else [])
    resolution_labels = ("1200p", "960p", "480p")
    channels = [
        {
            "channel_index": index,
            "name": f"Kanal {index + 1} · {resolution_labels[index] if index < len(resolution_labels) else 'ONVIF'}",
            "stream_uri": uri,
        }
        for index, uri in enumerate(channel_uris)
    ]
    return CameraSnapshot(
        status=status,
        message=" | ".join(messages),
        manufacturer=onvif_probe.manufacturer or "Aqara",
        model=onvif_probe.model,
        firmware=onvif_probe.firmware,
        serial=onvif_probe.serial,
        stream_uri=stream_uri,
        detections=catalog_rows(onvif_probe.event_detection_keys),
        channels=channels,
    )


def _is_authentication_error(message: str) -> bool:
    normalized = str(message).lower()
    return "401" in normalized or "unauthorized" in normalized or "authentication" in normalized
