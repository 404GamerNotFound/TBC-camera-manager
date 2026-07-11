from __future__ import annotations

import logging
from importlib import metadata
from functools import lru_cache
from typing import Any

from .base import CameraModule

LOGGER = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "tbc.camera_modules"


class UnknownCameraModuleError(LookupError):
    pass


def _builtin_modules() -> tuple[CameraModule, ...]:
    from ..reolink.module import ReolinkCameraModule
    from ..tplink.module import TpLinkCameraModule

    return (ReolinkCameraModule(), TpLinkCameraModule())


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
def list_camera_modules() -> tuple[CameraModule, ...]:
    by_key: dict[str, CameraModule] = {}
    for module in (*_builtin_modules(), *_load_installed_modules()):
        key = str(module.key).strip().lower()
        if not key or key in by_key:
            if key in by_key:
                LOGGER.warning("Doppeltes Kamera-Modul %s wird ignoriert", key)
            continue
        by_key[key] = module
    return tuple(by_key.values())


def get_camera_module(key: str | None) -> CameraModule:
    normalized = str(key or "reolink").strip().lower()
    for module in list_camera_modules():
        if str(module.key).strip().lower() == normalized:
            return module
    raise UnknownCameraModuleError(f"Kamera-Modul '{normalized}' ist nicht installiert")
