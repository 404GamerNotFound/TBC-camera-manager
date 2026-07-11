from __future__ import annotations

from typing import Any

from ..camera_modules.base import CameraCapability, CameraModule, CameraSnapshot
from .catalog import definitions
from .service import probe_camera


class AqaraCameraModule(CameraModule):
    key = "aqara"
    label = "Aqara"
    description = "Aqara-Kameras sowie kompatible Video-Türklingeln"
    default_onvif_port = 5000
    default_http_port = 80
    default_rtsp_port = 8554
    capabilities = frozenset({CameraCapability.LIVE, CameraCapability.DETECTIONS, CameraCapability.CHANNELS})

    def detection_definitions(self) -> tuple[Any, ...]:
        return definitions()

    async def probe(self, camera: dict[str, Any]) -> CameraSnapshot:
        return await probe_camera(camera)
