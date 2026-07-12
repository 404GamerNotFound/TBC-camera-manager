from __future__ import annotations

from datetime import datetime
from typing import Any

from tbc_camera_api import CameraCapability, CameraModule, CameraSnapshot
from .catalog import definitions
from .control import check_firmware, get_control_state, run_firmware_update, send_control
from .sdcard import list_sd_card_recordings, open_sd_card_download
from .service import probe_camera


class ReolinkCameraModule(CameraModule):
    key = "reolink"
    label = "Reolink"
    description = "Reolink-Kameras und NVR via ONVIF und reolink-aio"
    capabilities = frozenset(
        {
            CameraCapability.LIVE,
            CameraCapability.RECORDING,
            CameraCapability.DETECTIONS,
            CameraCapability.CHANNELS,
            CameraCapability.ARCHIVE,
            CameraCapability.CONTROL,
            CameraCapability.FIRMWARE,
        }
    )

    def detection_definitions(self) -> tuple[Any, ...]:
        return definitions()

    async def probe(self, camera: dict[str, Any]) -> CameraSnapshot:
        return await probe_camera(camera)

    async def list_archive_recordings(
        self,
        camera: dict[str, Any],
        *,
        channel: int,
        start: datetime,
        end: datetime,
        stream: str = "main",
    ) -> list[dict[str, Any]]:
        return await list_sd_card_recordings(
            camera,
            channel=channel,
            start=start,
            end=end,
            stream=stream,
        )

    async def open_archive_download(
        self,
        camera: dict[str, Any],
        *,
        channel: int,
        source: str,
        start_id: str,
        end_id: str,
        stream: str = "main",
    ) -> Any:
        return await open_sd_card_download(
            camera,
            channel=channel,
            source=source,
            start_id=start_id,
            end_id=end_id,
            stream=stream,
        )

    async def get_control_state(self, camera: dict[str, Any], *, channel: int = 0) -> dict[str, Any]:
        return await get_control_state(camera, channel=channel)

    async def send_control(self, camera: dict[str, Any], *, action: str, channel: int = 0, **params: Any) -> dict[str, Any]:
        return await send_control(camera, action=action, channel=channel, **params)

    async def check_firmware(self, camera: dict[str, Any], *, channel: int = 0) -> dict[str, Any]:
        return await check_firmware(camera, channel=channel)

    async def update_firmware(
        self,
        camera: dict[str, Any],
        *,
        channel: int = 0,
        progress_callback: Any = None,
    ) -> None:
        await run_firmware_update(camera, channel=channel, progress_callback=progress_callback)
