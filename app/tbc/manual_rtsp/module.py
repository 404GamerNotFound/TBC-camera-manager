from __future__ import annotations

import asyncio
from typing import Any

from ..camera_modules.base import CameraCapability, CameraModule, CameraSnapshot
from ..camera_modules.streams import probe_rtsp_stream, validate_manual_stream_uri


class ManualRtspCameraModule(CameraModule):
    supports_manual_stream_uri = True
    requires_manual_stream_uri = True
    requires_credentials = False
    capabilities = frozenset({CameraCapability.LIVE})

    def __init__(
        self,
        *,
        manufacturer: str,
        model_hint: str,
        setup_hint: str,
    ) -> None:
        self.manufacturer_name = manufacturer
        self.model_hint = model_hint
        self.setup_hint = setup_hint

    async def probe(self, camera: dict[str, Any]) -> CameraSnapshot:
        raw_uri = str(camera.get("manual_stream_uri") or "")
        try:
            stream_uri = validate_manual_stream_uri(raw_uri)
        except ValueError as exc:
            return CameraSnapshot(
                status="error",
                message=f"{exc} | {self.setup_hint}",
                manufacturer=self.manufacturer_name,
                model=self.model_hint,
            )

        probe_status, probe_message = await asyncio.to_thread(probe_rtsp_stream, stream_uri)
        status = "warn" if probe_status == "warning" else probe_status
        return CameraSnapshot(
            status=status,
            message=f"{probe_message} | {self.setup_hint}",
            manufacturer=self.manufacturer_name,
            model=self.model_hint,
            stream_uri=stream_uri,
        )
