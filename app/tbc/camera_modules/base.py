from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Protocol


class CameraCapability(str, Enum):
    LIVE = "live"
    RECORDING = "recording"
    DETECTIONS = "detections"
    CHANNELS = "channels"
    ARCHIVE = "archive"
    CONTROL = "control"
    FIRMWARE = "firmware"


@dataclass
class CameraSnapshot:
    status: str
    message: str
    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    serial: str | None = None
    stream_uri: str | None = None
    detections: list[dict[str, Any]] = field(default_factory=list)
    channels: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, int | float] = field(default_factory=dict)


class ModuleFeatureUnsupported(RuntimeError):
    pass


class ArchiveDownload(Protocol):
    filename: str
    length: int

    def chunks(self, chunk_size: int = 65536) -> AsyncIterator[bytes]: ...


class CameraModule(ABC):
    """Public contract implemented by built-in and installed camera modules."""

    key: str
    label: str
    description: str = ""
    default_onvif_port: int = 8000
    default_http_port: int = 80
    default_rtsp_port: int = 554
    supports_manual_stream_uri: bool = False
    requires_manual_stream_uri: bool = False
    requires_credentials: bool = True
    capabilities: frozenset[CameraCapability] = frozenset()

    def supports(self, capability: CameraCapability) -> bool:
        return capability in self.capabilities

    def detection_definitions(self) -> tuple[Any, ...]:
        return ()

    @abstractmethod
    async def probe(self, camera: dict[str, Any]) -> CameraSnapshot:
        raise NotImplementedError

    async def list_archive_recordings(
        self,
        camera: dict[str, Any],
        *,
        channel: int,
        start: datetime,
        end: datetime,
        stream: str = "main",
    ) -> list[dict[str, Any]]:
        raise ModuleFeatureUnsupported(f"The {self.label} module does not support a camera archive")

    async def open_archive_download(
        self,
        camera: dict[str, Any],
        *,
        channel: int,
        source: str,
        start_id: str,
        end_id: str,
        stream: str = "main",
    ) -> ArchiveDownload:
        raise ModuleFeatureUnsupported(f"The {self.label} module does not support a camera archive")

    async def get_control_state(self, camera: dict[str, Any], *, channel: int = 0) -> dict[str, Any]:
        raise ModuleFeatureUnsupported(f"The {self.label} module does not support camera control")

    async def send_control(self, camera: dict[str, Any], *, action: str, channel: int = 0, **params: Any) -> dict[str, Any]:
        raise ModuleFeatureUnsupported(f"The {self.label} module does not support camera control")

    async def check_firmware(self, camera: dict[str, Any], *, channel: int = 0) -> dict[str, Any]:
        raise ModuleFeatureUnsupported(f"The {self.label} module does not support firmware checks")

    async def update_firmware(
        self,
        camera: dict[str, Any],
        *,
        channel: int = 0,
        progress_callback: Any = None,
    ) -> None:
        raise ModuleFeatureUnsupported(f"The {self.label} module does not support firmware updates")
