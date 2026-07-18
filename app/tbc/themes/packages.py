from __future__ import annotations

import json
import re
import shutil
import stat
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from .base import ThemeManifest, ThemePackage

THEME_SCHEMA_VERSION = 1
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
MAX_EXTRACTED_BYTES = 10 * 1024 * 1024
MAX_FILES = 100
THEME_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
# Themes ship no executable code, unlike camera plugins: only stylesheets,
# metadata and image assets are ever installed or served from a theme package.
ALLOWED_SUFFIXES = {".css", ".json", ".md", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".ico"}
ALLOWED_BARE_FILENAMES = {"LICENSE", "COPYING", "NOTICE"}


class ThemePackageError(ValueError):
    pass


def builtin_themes_path() -> Path:
    return Path(__file__).resolve().parents[1] / "design_themes"


def discover_theme_packages(external_path: str) -> tuple[ThemePackage, ...]:
    packages: list[ThemePackage] = []
    seen: set[str] = set()
    for root, builtin in ((builtin_themes_path(), True), (Path(external_path), False)):
        if not root.exists():
            continue
        for path in sorted(root.iterdir()):
            if not path.is_dir() or not (path / "manifest.json").is_file():
                continue
            manifest = read_manifest(path / "manifest.json")
            if manifest.key in seen:
                continue
            if not (path / "static" / manifest.stylesheet).is_file():
                continue
            packages.append(ThemePackage(manifest=manifest, path=path, builtin=builtin))
            seen.add(manifest.key)
    return tuple(packages)


def read_manifest(path: Path) -> ThemeManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThemePackageError(f"Manifest konnte nicht gelesen werden: {exc}") from exc
    if not isinstance(raw, dict):
        raise ThemePackageError("manifest.json must contain a JSON object")
    try:
        schema_version = int(raw.get("schema_version") or 0)
    except (TypeError, ValueError) as exc:
        raise ThemePackageError("The design schema version must be a number") from exc
    if schema_version != THEME_SCHEMA_VERSION:
        raise ThemePackageError(f"Unsupported design schema version: {schema_version}")
    key = str(raw.get("key") or "").strip().lower()
    if not THEME_KEY_PATTERN.fullmatch(key):
        raise ThemePackageError("Invalid design key")
    label = str(raw.get("label") or "").strip()
    version = str(raw.get("version") or "").strip()
    if not label or not version:
        raise ThemePackageError("Design name and version are required")
    stylesheet = str(raw.get("stylesheet") or "styles.css").strip()
    stylesheet_path = PurePosixPath(stylesheet)
    if (
        stylesheet_path.is_absolute()
        or ".." in stylesheet_path.parts
        or len(stylesheet_path.parts) != 1
        or stylesheet_path.suffix != ".css"
    ):
        raise ThemePackageError("Invalid stylesheet in the design manifest")
    return ThemeManifest(
        schema_version=schema_version,
        key=key,
        label=label,
        version=version,
        description=str(raw.get("description") or "").strip(),
        stylesheet=stylesheet,
    )


def install_theme_archive(archive: bytes, external_path: str) -> ThemePackage:
    if not archive or len(archive) > MAX_ARCHIVE_BYTES:
        raise ThemePackageError("The design file is empty or larger than 5 MB")
    root = Path(external_path)
    root.mkdir(parents=True, exist_ok=True)
    try:
        bundle = zipfile.ZipFile(BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise ThemePackageError("The design file is not a valid ZIP archive") from exc
    with bundle:
        members, prefix = _validated_members(bundle)
        manifest_member = next(member for member in members if _relative_name(member.filename, prefix) == "manifest.json")
        try:
            manifest_raw = bundle.read(manifest_member)
        except OSError as exc:
            raise ThemePackageError(f"Manifest konnte nicht gelesen werden: {exc}") from exc
        with tempfile.TemporaryDirectory(prefix=".design-theme-", dir=root) as temp_dir:
            staging = Path(temp_dir) / "package"
            staging.mkdir()
            for member in members:
                relative = _relative_name(member.filename, prefix)
                if not relative or member.is_dir():
                    continue
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
            (staging / "manifest.json").write_bytes(manifest_raw)
            manifest = read_manifest(staging / "manifest.json")
            if not (staging / "static" / manifest.stylesheet).is_file():
                raise ThemePackageError("The design archive does not contain the stylesheet specified in the manifest")
            if (builtin_themes_path() / manifest.key).exists():
                raise ThemePackageError("Built-in designs cannot be overwritten")
            package = ThemePackage(manifest=manifest, path=staging, builtin=False)
            target = root / manifest.key
            backup = root / f".{manifest.key}.backup"
            if backup.exists():
                shutil.rmtree(backup)
            if target.exists():
                target.replace(backup)
            try:
                staging.replace(target)
            except Exception:
                if backup.exists():
                    backup.replace(target)
                raise
            if backup.exists():
                shutil.rmtree(backup)
    return ThemePackage(manifest=manifest, path=target, builtin=False)


def export_theme_archive(package: ThemePackage) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(package.path.rglob("*")):
            if not path.is_file():
                continue
            bundle.write(path, path.relative_to(package.path).as_posix())
    return output.getvalue()


def remove_external_theme(key: str, external_path: str) -> None:
    normalized = str(key).strip().lower()
    if not THEME_KEY_PATTERN.fullmatch(normalized):
        raise ThemePackageError("Invalid design key")
    if (builtin_themes_path() / normalized).exists():
        raise ThemePackageError("Built-in designs cannot be removed")
    target = Path(external_path) / normalized
    if not target.is_dir():
        raise ThemePackageError("The design is not installed")
    shutil.rmtree(target)


def _validated_members(bundle: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], str]:
    members = bundle.infolist()
    if not members or len(members) > MAX_FILES:
        raise ThemePackageError("The design archive contains too many files or no files")
    total_size = 0
    manifest_candidates: list[str] = []
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
            raise ThemePackageError("The design archive contains an unsafe file path")
        mode = member.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise ThemePackageError("Symbolic links are not allowed in designs")
        if (
            not member.is_dir()
            and path.suffix.lower() not in ALLOWED_SUFFIXES
            and path.name not in ALLOWED_BARE_FILENAMES
        ):
            raise ThemePackageError(f"Nicht erlaubter Dateityp: {path.suffix or member.filename}")
        total_size += member.file_size
        if total_size > MAX_EXTRACTED_BYTES:
            raise ThemePackageError("The extracted design is larger than 10 MB")
        if path.name == "manifest.json" and len(path.parts) <= 2:
            manifest_candidates.append(member.filename)
    if len(manifest_candidates) != 1:
        raise ThemePackageError("The design must contain exactly one manifest.json in its root directory")
    manifest_path = PurePosixPath(manifest_candidates[0])
    prefix = f"{manifest_path.parts[0]}/" if len(manifest_path.parts) == 2 else ""
    for member in members:
        if prefix and not member.filename.startswith(prefix):
            raise ThemePackageError("All design files must be in the same root directory")
    return members, prefix


def _relative_name(filename: str, prefix: str) -> str:
    return filename[len(prefix):] if prefix else filename
