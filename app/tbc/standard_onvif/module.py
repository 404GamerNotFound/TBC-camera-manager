from __future__ import annotations

from typing import Any

from ..camera_modules.base import CameraCapability, CameraModule, CameraSnapshot
from .catalog import definitions
from .service import probe_camera


class StandardOnvifCameraModule(CameraModule):
    key = "standard_onvif"
    label = "Standard ONVIF Verbindung"
    description = "Herstellerneutraler ONVIF-Fallback für weitere Kameramodelle"
    default_onvif_port = 80
    default_http_port = 80
    default_rtsp_port = 554
    capabilities = frozenset({CameraCapability.LIVE, CameraCapability.DETECTIONS})

    def detection_definitions(self) -> tuple[Any, ...]:
        return definitions()

    async def probe(self, camera: dict[str, Any]) -> CameraSnapshot:
        return await probe_camera(camera)
