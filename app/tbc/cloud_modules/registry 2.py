from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from ..config import load_settings
from .base import CloudAccountModule
from .packages import CloudPluginPackage, discover_plugin_packages, load_plugin_module

LOGGER = logging.getLogger(__name__)


class UnknownCloudModuleError(LookupError):
    pass


@dataclass(frozen=True)
class CloudModuleRegistration:
    module: CloudAccountModule
    origin: str
    version: str
    package: CloudPluginPackage


@lru_cache(maxsize=1)
def list_cloud_module_registrations() -> tuple[CloudModuleRegistration, ...]:
    by_key: dict[str, CloudModuleRegistration] = {}
    settings = load_settings()
    for package in discover_plugin_packages(settings.cloud_modules_path):
        try:
            module = load_plugin_module(package)
        except Exception:
            LOGGER.exception("Cloud-Plugin %s konnte nicht geladen werden", package.manifest.key)
            continue
        origin = "builtin" if package.builtin else "uploaded"
        by_key[module.key] = CloudModuleRegistration(
            module=module,
            origin=origin,
            version=package.manifest.version,
            package=package,
        )
    return tuple(by_key.values())


def list_cloud_modules() -> tuple[CloudAccountModule, ...]:
    return tuple(registration.module for registration in list_cloud_module_registrations())


def reload_cloud_modules() -> None:
    list_cloud_module_registrations.cache_clear()


def get_cloud_module(key: str | None) -> CloudAccountModule:
    normalized = str(key or "").strip().lower()
    for module in list_cloud_modules():
        if str(module.key).strip().lower() == normalized:
            return module
    raise UnknownCloudModuleError(f"Cloud-Modul '{normalized}' ist nicht installiert")
