from __future__ import annotations

from typing import Any

from tbc_camera_api import CameraCapability, CameraModule, CameraSnapshot
from .catalog import definitions
from .control import get_control_state, send_control
from .service import probe_camera


class AqaraCameraModule(CameraModule):
    key = "aqara"
    label = "Aqara"
    description = "Aqara-Kameras sowie kompatible Video-Türklingeln"
    default_onvif_port = 5000
    default_http_port = 80
    default_rtsp_port = 8554
    capabilities = frozenset(
        {
            CameraCapability.LIVE,
            CameraCapability.DETECTIONS,
            CameraCapability.CHANNELS,
            CameraCapability.CONTROL,
        }
    )

    def detection_definitions(self) -> tuple[Any, ...]:
        return definitions()

    async def probe(self, camera: dict[str, Any]) -> CameraSnapshot:
        return await probe_camera(camera)

    async def get_control_state(self, camera: dict[str, Any], *, channel: int = 0) -> dict[str, Any]:
        return await get_control_state(camera)

    async def send_control(self, camera: dict[str, Any], *, action: str, channel: int = 0, **params: Any) -> dict[str, Any]:
        return await send_control(camera, action=action, **params)
