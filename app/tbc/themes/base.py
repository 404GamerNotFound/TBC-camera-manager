from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ThemeManifest:
    schema_version: int
    key: str
    label: str
    version: str
    description: str
    stylesheet: str


@dataclass(frozen=True)
class ThemePackage:
    manifest: ThemeManifest
    path: Path
    builtin: bool
