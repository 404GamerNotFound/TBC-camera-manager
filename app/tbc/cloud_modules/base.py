from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class CloudAuthType(str, Enum):
    CREDENTIALS = "credentials"
    TOKEN = "token"


class CloudAccountFieldType(str, Enum):
    TEXT = "text"
    EMAIL = "email"
    PASSWORD = "password"
    NUMBER = "number"
    CHECKBOX = "checkbox"
    SELECT = "select"


class CloudConnectionError(RuntimeError):
    """Raised by test_connection()/discover_devices() on any login or API failure."""


class CloudAccountValidationError(ValueError):
    """Raised when submitted plugin account fields are invalid."""


@dataclass(frozen=True)
class CloudAccountFieldOption:
    value: str
    label: str


@dataclass(frozen=True)
class CloudAccountField:
    """Provider-owned description of one field in the cloud-account form."""

    key: str
    label: str
    field_type: CloudAccountFieldType = CloudAccountFieldType.TEXT
    required: bool = False
    placeholder: str = ""
    help_text: str = ""
    autocomplete: str = ""
    default: str | int | bool | None = None
    minimum: int | None = None
    maximum: int | None = None
    full_width: bool = False
    options: tuple[CloudAccountFieldOption, ...] = ()


def normalize_account_configuration(
    fields: tuple[CloudAccountField, ...], submitted: Mapping[str, Any]
) -> dict[str, str | int | bool]:
    """Validate and coerce submitted values using only the selected plugin schema."""

    result: dict[str, str | int | bool] = {}
    for field in fields:
        raw = submitted.get(field.key)
        if field.field_type == CloudAccountFieldType.CHECKBOX:
            value = str(raw or "").strip().lower() in {"1", "true", "yes", "on"}
            if field.required and not value:
                raise CloudAccountValidationError(f"{field.label} muss aktiviert sein")
            result[field.key] = value
            continue

        fallback = field.default if field.default is not None else ""
        value = str(raw if raw is not None else fallback).strip()
        if field.required and not value:
            raise CloudAccountValidationError(f"{field.label} ist erforderlich")
        if not value:
            result[field.key] = ""
            continue
        if field.field_type == CloudAccountFieldType.NUMBER:
            try:
                number = int(value)
            except ValueError as exc:
                raise CloudAccountValidationError(f"{field.label} muss eine ganze Zahl sein") from exc
            if field.minimum is not None and number < field.minimum:
                raise CloudAccountValidationError(f"{field.label} muss mindestens {field.minimum} sein")
            if field.maximum is not None and number > field.maximum:
                raise CloudAccountValidationError(f"{field.label} darf höchstens {field.maximum} sein")
            result[field.key] = number
            continue
        if field.field_type == CloudAccountFieldType.SELECT:
            allowed = {option.value for option in field.options}
            if value not in allowed:
                raise CloudAccountValidationError(f"Ungültige Auswahl für {field.label}")
        result[field.key] = value
    return result


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
    account_fields: tuple[CloudAccountField, ...] = ()

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
