from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from typing import Any

from ..config import load_settings
from .base import CameraModule
from .packages import PluginPackage, discover_plugin_packages, load_plugin_module

LOGGER = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "tbc.camera_modules"


class UnknownCameraModuleError(LookupError):
    pass


@dataclass(frozen=True)
class CameraModuleRegistration:
    module: CameraModule
    origin: str
    version: str
    package: PluginPackage | None = None


def _entry_points() -> list[Any]:
    discovered = metadata.entry_points()
    if hasattr(discovered, "select"):
        return list(discovered.select(group=ENTRY_POINT_GROUP))
    return list(discovered.get(ENTRY_POINT_GROUP, ()))


def _load_installed_modules() -> list[CameraModule]:
    modules: list[CameraModule] = []
    for entry_point in _entry_points():
        try:
            loaded = entry_point.load()
            module = loaded() if isinstance(loaded, type) else loaded
            if not isinstance(module, CameraModule):
                raise TypeError("entry point does not provide a CameraModule")
            modules.append(module)
        except Exception:
            LOGGER.exception("Kamera-Modul %s konnte nicht geladen werden", entry_point.name)
    return modules


@lru_cache(maxsize=1)
def list_camera_module_registrations() -> tuple[CameraModuleRegistration, ...]:
    by_key: dict[str, CameraModuleRegistration] = {}
    settings = load_settings()
    for package in discover_plugin_packages(settings.camera_modules_path):
        try:
            module = load_plugin_module(package)
        except Exception:
            LOGGER.exception("Kamera-Plugin %s konnte nicht geladen werden", package.manifest.key)
            continue
        origin = "builtin" if package.builtin else "uploaded"
        by_key[module.key] = CameraModuleRegistration(
            module=module,
            origin=origin,
            version=package.manifest.version,
            package=package,
        )
    for module in _load_installed_modules():
        key = str(module.key).strip().lower()
        if not key or key in by_key:
            if key in by_key:
                LOGGER.warning("Doppeltes Kamera-Modul %s wird ignoriert", key)
            continue
        by_key[key] = CameraModuleRegistration(module=module, origin="entrypoint", version="extern")
    return tuple(by_key.values())


def list_camera_modules() -> tuple[CameraModule, ...]:
    return tuple(registration.module for registration in list_camera_module_registrations())


def reload_camera_modules() -> None:
    list_camera_module_registrations.cache_clear()


def get_camera_module(key: str | None) -> CameraModule:
    normalized = str(key or "reolink").strip().lower()
    for module in list_camera_modules():
        if str(module.key).strip().lower() == normalized:
            return module
    raise UnknownCameraModuleError(f"Kamera-Modul '{normalized}' ist nicht installiert")
