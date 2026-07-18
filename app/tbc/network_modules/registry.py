from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from ..config import load_settings
from .base import NetworkAccountModule
from .packages import NetworkPluginPackage, discover_plugin_packages, load_plugin_module

LOGGER = logging.getLogger(__name__)


class UnknownNetworkModuleError(LookupError):
    pass


@dataclass(frozen=True)
class NetworkModuleRegistration:
    module: NetworkAccountModule
    origin: str
    version: str
    package: NetworkPluginPackage


@lru_cache(maxsize=1)
def list_network_module_registrations() -> tuple[NetworkModuleRegistration, ...]:
    by_key: dict[str, NetworkModuleRegistration] = {}
    settings = load_settings()
    for package in discover_plugin_packages(settings.network_modules_path):
        try:
            module = load_plugin_module(package)
        except Exception:
            LOGGER.exception("Netzwerk-Plugin %s konnte nicht geladen werden", package.manifest.key)
            continue
        origin = "builtin" if package.builtin else "uploaded"
        by_key[module.key] = NetworkModuleRegistration(
            module=module,
            origin=origin,
            version=package.manifest.version,
            package=package,
        )
    return tuple(by_key.values())


def list_network_modules() -> tuple[NetworkAccountModule, ...]:
    return tuple(registration.module for registration in list_network_module_registrations())


def reload_network_modules() -> None:
    list_network_module_registrations.cache_clear()


def get_network_module(key: str | None) -> NetworkAccountModule:
    normalized = str(key or "").strip().lower()
    for module in list_network_modules():
        if str(module.key).strip().lower() == normalized:
            return module
    raise UnknownNetworkModuleError(f"Netzwerk-Modul '{normalized}' ist nicht installiert")
