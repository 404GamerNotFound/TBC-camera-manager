from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CloudAuthType(str, Enum):
    CREDENTIALS = "credentials"
    TOKEN = "token"


class CloudConnectionError(RuntimeError):
    """Raised by test_connection()/discover_devices() on any login or API failure."""


@dataclass(frozen=True)
class CloudDevice:
    """One camera a cloud-account module found while talking to the vendor's account API.

    `manual_stream_uri`, when set, can be handed straight to TBC's existing
    manual-RTSP camera modules (`rtsp_only`, `ubiquiti`, ...) - a cloud-account
    plugin does not need its own CameraModule as long as the vendor's account
    API resolves each device down to a plain RTSP/RTSPS URI. See
    docs/cloud-accounts.md.
    """

    external_id: str
    name: str
    model: str | None = None
    online: bool | None = None
    manual_stream_uri: str | None = None
    suggested_module_key: str = "rtsp_only"


class CloudAccountModule(ABC):
    """Public contract implemented by built-in and installed cloud-account modules."""

    key: str
    label: str
    description: str = ""
    auth_type: CloudAuthType = CloudAuthType.CREDENTIALS
    identifier_label: str = "Benutzername"
    secret_label: str = "Passwort"
    requires_host: bool = False
    default_port: int = 443

    @abstractmethod
    async def test_connection(self, account: dict[str, Any]) -> str:
        """Log in and return a short, human-readable status message.

        Must raise CloudConnectionError (or a subclass) on any failure instead
        of returning an error string, so callers can distinguish success from
        failure without parsing text.
        """
        raise NotImplementedError

    @abstractmethod
    async def discover_devices(self, account: dict[str, Any]) -> list[CloudDevice]:
        raise NotImplementedError
