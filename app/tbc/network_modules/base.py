from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class NetworkAccountFieldType(str, Enum):
    TEXT = "text"
    EMAIL = "email"
    PASSWORD = "password"
    NUMBER = "number"
    CHECKBOX = "checkbox"
    SELECT = "select"


class NetworkConnectionError(RuntimeError):
    """Raised by discover_devices() on any login or API failure."""


class NetworkAccountValidationError(ValueError):
    """Raised when submitted plugin account fields are invalid."""


@dataclass(frozen=True)
class NetworkAccountFieldOption:
    value: str
    label: str


@dataclass(frozen=True)
class NetworkAccountField:
    """Provider-owned description of one field in the network-account form."""

    key: str
    label: str
    field_type: NetworkAccountFieldType = NetworkAccountFieldType.TEXT
    required: bool = False
    placeholder: str = ""
    help_text: str = ""
    autocomplete: str = ""
    default: str | int | bool | None = None
    minimum: int | None = None
    maximum: int | None = None
    full_width: bool = False
    options: tuple[NetworkAccountFieldOption, ...] = ()


def normalize_account_configuration(
    fields: tuple[NetworkAccountField, ...], submitted: Mapping[str, Any]
) -> dict[str, str | int | bool]:
    """Validate and coerce submitted values using only the selected plugin schema."""

    result: dict[str, str | int | bool] = {}
    for field in fields:
        raw = submitted.get(field.key)
        if field.field_type == NetworkAccountFieldType.CHECKBOX:
            value = str(raw or "").strip().lower() in {"1", "true", "yes", "on"}
            if field.required and not value:
                raise NetworkAccountValidationError(f"{field.label} muss aktiviert sein")
            result[field.key] = value
            continue

        fallback = field.default if field.default is not None else ""
        value = str(raw if raw is not None else fallback).strip()
        if field.required and not value:
            raise NetworkAccountValidationError(f"{field.label} ist erforderlich")
        if not value:
            result[field.key] = ""
            continue
        if field.field_type == NetworkAccountFieldType.NUMBER:
            try:
                number = int(value)
            except ValueError as exc:
                raise NetworkAccountValidationError(f"{field.label} muss eine ganze Zahl sein") from exc
            if field.minimum is not None and number < field.minimum:
                raise NetworkAccountValidationError(f"{field.label} muss mindestens {field.minimum} sein")
            if field.maximum is not None and number > field.maximum:
                raise NetworkAccountValidationError(f"{field.label} must be at most {field.maximum}")
            result[field.key] = number
            continue
        if field.field_type == NetworkAccountFieldType.SELECT:
            allowed = {option.value for option in field.options}
            if value not in allowed:
                raise NetworkAccountValidationError(f"Invalid selection for {field.label}")
        result[field.key] = value
    return result


@dataclass(frozen=True)
class NetworkDevice:
    """One network client a network-account module found on the controller.

    `mac_address` is the stable identifier TBC stores on a camera to keep the
    mapping durable across DHCP lease/IP changes - see docs/network-accounts.md.
    """

    mac_address: str
    name: str
    ip_address: str | None = None
    online: bool | None = None
    connection_type: str | None = None
    uplink_name: str | None = None
    signal_dbm: int | None = None
    last_seen: str | None = None


class NetworkAccountModule(ABC):
    """Public contract implemented by built-in and installed network-account modules."""

    key: str
    label: str
    description: str = ""
    default_port: int = 443
    account_fields: tuple[NetworkAccountField, ...] = ()

    @abstractmethod
    async def discover_devices(self, account: dict[str, Any]) -> list[NetworkDevice]:
        """Log in and return every client the controller currently knows about.

        Must raise NetworkConnectionError (or a subclass) on any login/API
        failure instead of returning an empty list, so callers can
        distinguish "no devices" from "could not connect" - this single
        method also serves as the account's connection test, since a
        controller client-list call is the cheapest available login check.
        """
        raise NotImplementedError
