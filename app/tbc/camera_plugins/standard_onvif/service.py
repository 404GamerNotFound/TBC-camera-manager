from __future__ import annotations

import asyncio
from typing import Any

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
        channels=_channels_for(onvif_probe, camera),
    )


def _channels_for(onvif_probe: Any, camera: dict[str, Any]) -> list[dict[str, Any]]:
    # A camera with a single lens keeps the plain stream_uri above and has
    # no channels - only cameras where the ONVIF probe found more than one
    # physical lens (distinct VideoSource) get a channel per lens, so each
    # lens can be viewed/recorded independently instead of only the first
    # one ever being reachable.
    if len(onvif_probe.stream_profiles) <= 1:
        return []
    return [
        {
            "channel_index": index,
            "name": f"Lens {index + 1}",
            "stream_uri": rtsp_uri_with_credentials(profile.uri, camera["username"], camera["password"]),
        }
        for index, profile in enumerate(onvif_probe.stream_profiles)
    ]
