from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..config import load_settings
from .base import ThemeManifest
from .packages import ThemePackage, discover_theme_packages


class UnknownThemeError(LookupError):
    pass


@dataclass(frozen=True)
class ThemeRegistration:
    manifest: ThemeManifest
    origin: str
    package: ThemePackage


@lru_cache(maxsize=1)
def list_theme_registrations() -> tuple[ThemeRegistration, ...]:
    settings = load_settings()
    registrations = tuple(
        ThemeRegistration(
            manifest=package.manifest,
            origin="builtin" if package.builtin else "uploaded",
            package=package,
        )
        for package in discover_theme_packages(settings.theme_modules_path)
    )
    return registrations


def list_themes() -> tuple[ThemeManifest, ...]:
    return tuple(registration.manifest for registration in list_theme_registrations())


def reload_themes() -> None:
    list_theme_registrations.cache_clear()


def get_theme_registration(key: str | None) -> ThemeRegistration:
    normalized = str(key or "standard").strip().lower()
    for registration in list_theme_registrations():
        if registration.manifest.key == normalized:
            return registration
    for registration in list_theme_registrations():
        if registration.manifest.key == "standard":
            return registration
    raise UnknownThemeError(f"Design '{normalized}' ist nicht installiert")
