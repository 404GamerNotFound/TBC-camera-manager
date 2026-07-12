from __future__ import annotations

import importlib
import importlib.util
import json
import re
import shutil
import stat
import sys
import tempfile
import types
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from .base import CloudAccountModule, CloudAuthType, CloudConnectionError, CloudDevice

PLUGIN_SCHEMA_VERSION = 1
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_BYTES = 25 * 1024 * 1024
MAX_FILES = 200
PLUGIN_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
ALLOWED_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".txt"}


class CloudPluginError(ValueError):
    pass


@dataclass(frozen=True)
class CloudPluginManifest:
    schema_version: int
    key: str
    label: str
    version: str
    description: str
    entrypoint: str
    auth_type: CloudAuthType
    identifier_label: str
    secret_label: str
    requires_host: bool
    default_port: int


@dataclass(frozen=True)
class CloudPluginPackage:
    manifest: CloudPluginManifest
    path: Path
    builtin: bool


def builtin_plugins_path() -> Path:
    return Path(__file__).resolve().parents[1] / "cloud_plugins"


def discover_plugin_packages(external_path: str) -> tuple[CloudPluginPackage, ...]:
    packages: list[CloudPluginPackage] = []
    seen: set[str] = set()
    for root, builtin in ((builtin_plugins_path(), True), (Path(external_path), False)):
        if not root.exists():
            continue
        for path in sorted(root.iterdir()):
            if not path.is_dir() or not (path / "manifest.json").is_file():
                continue
            manifest = read_manifest(path / "manifest.json")
            if manifest.key in seen:
                continue
            packages.append(CloudPluginPackage(manifest=manifest, path=path, builtin=builtin))
            seen.add(manifest.key)
    return tuple(packages)


def read_manifest(path: Path) -> CloudPluginManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CloudPluginError(f"Manifest konnte nicht gelesen werden: {exc}") from exc
    if not isinstance(raw, dict):
        raise CloudPluginError("manifest.json muss ein JSON-Objekt enthalten")
    try:
        schema_version = int(raw.get("schema_version") or 0)
    except (TypeError, ValueError) as exc:
        raise CloudPluginError("Plugin-Schemaversion muss eine Zahl sein") from exc
    if schema_version != PLUGIN_SCHEMA_VERSION:
        raise CloudPluginError(f"Nicht unterstützte Plugin-Schemaversion: {schema_version}")
    key = str(raw.get("key") or "").strip().lower()
    if not PLUGIN_KEY_PATTERN.fullmatch(key):
        raise CloudPluginError("Ungültiger Plugin-Schlüssel")
    label = str(raw.get("label") or "").strip()
    version = str(raw.get("version") or "").strip()
    if not label or not version:
        raise CloudPluginError("Plugin-Name und Version sind erforderlich")
    entrypoint = str(raw.get("entrypoint") or "plugin.py").strip()
    entrypoint_path = PurePosixPath(entrypoint)
    if (
        entrypoint_path.is_absolute()
        or ".." in entrypoint_path.parts
        or len(entrypoint_path.parts) != 1
        or entrypoint_path.suffix != ".py"
    ):
        raise CloudPluginError("Ungültiger Plugin-Einstiegspunkt")
    try:
        auth_type = CloudAuthType(str(raw.get("auth_type") or "credentials"))
    except ValueError as exc:
        raise CloudPluginError(f"Unbekannter Auth-Typ: {exc}") from exc
    try:
        default_port = int(raw.get("default_port") or 443)
    except (TypeError, ValueError) as exc:
        raise CloudPluginError("default_port muss eine Zahl sein") from exc
    if not 1 <= default_port <= 65535:
        raise CloudPluginError("default_port muss zwischen 1 und 65535 liegen")
    return CloudPluginManifest(
        schema_version=schema_version,
        key=key,
        label=label,
        version=version,
        description=str(raw.get("description") or "").strip(),
        entrypoint=entrypoint,
        auth_type=auth_type,
        identifier_label=str(raw.get("identifier_label") or "Benutzername").strip(),
        secret_label=str(raw.get("secret_label") or "Passwort").strip(),
        requires_host=bool(raw.get("requires_host", False)),
        default_port=default_port,
    )


def load_plugin_module(package: CloudPluginPackage) -> CloudAccountModule:
    entrypoint = package.path / package.manifest.entrypoint
    if not entrypoint.is_file():
        raise CloudPluginError(f"Plugin-Einstiegspunkt fehlt: {package.manifest.entrypoint}")
    import_name = f"tbc_cloud_plugin_{package.manifest.key}"
    _install_plugin_api()
    for loaded_name in tuple(sys.modules):
        if loaded_name == import_name or loaded_name.startswith(f"{import_name}."):
            sys.modules.pop(loaded_name, None)
    spec = importlib.util.spec_from_file_location(
        import_name,
        entrypoint,
        submodule_search_locations=[str(package.path)],
    )
    if spec is None or spec.loader is None:
        raise CloudPluginError("Plugin-Einstiegspunkt konnte nicht geladen werden")
    imported = importlib.util.module_from_spec(spec)
    sys.modules[import_name] = imported
    try:
        spec.loader.exec_module(imported)
        factory = getattr(imported, "create_module", None)
        module = factory() if callable(factory) else getattr(imported, "MODULE", None)
    except Exception as exc:
        sys.modules.pop(import_name, None)
        raise CloudPluginError(f"Plugin-Code konnte nicht geladen werden: {exc}") from exc
    if not isinstance(module, CloudAccountModule):
        raise CloudPluginError("plugin.py muss create_module() oder MODULE mit einem CloudAccountModule bereitstellen")
    manifest = package.manifest
    module.key = manifest.key
    module.label = manifest.label
    module.description = manifest.description
    module.auth_type = manifest.auth_type
    module.identifier_label = manifest.identifier_label
    module.secret_label = manifest.secret_label
    module.requires_host = manifest.requires_host
    module.default_port = manifest.default_port
    return module


def _install_plugin_api() -> None:
    api = types.ModuleType("tbc_cloud_api")
    api.CloudAccountModule = CloudAccountModule
    api.CloudAuthType = CloudAuthType
    api.CloudConnectionError = CloudConnectionError
    api.CloudDevice = CloudDevice
    tbc_package = __package__.rsplit(".cloud_modules", 1)[0]
    api.import_tbc = lambda module_path: importlib.import_module(f"{tbc_package}.{module_path}")
    sys.modules["tbc_cloud_api"] = api


def install_plugin_archive(archive: bytes, external_path: str) -> CloudPluginPackage:
    if not archive or len(archive) > MAX_ARCHIVE_BYTES:
        raise CloudPluginError("Plugin-Datei ist leer oder größer als 10 MB")
    root = Path(external_path)
    root.mkdir(parents=True, exist_ok=True)
    try:
        bundle = zipfile.ZipFile(BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise CloudPluginError("Plugin-Datei ist kein gültiges ZIP-Archiv") from exc
    with bundle:
        members, prefix = _validated_members(bundle)
        manifest_member = next(member for member in members if _relative_name(member.filename, prefix) == "manifest.json")
        try:
            manifest_raw = bundle.read(manifest_member)
        except OSError as exc:
            raise CloudPluginError(f"Manifest konnte nicht gelesen werden: {exc}") from exc
        with tempfile.TemporaryDirectory(prefix=".cloud-plugin-", dir=root) as temp_dir:
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
            if (builtin_plugins_path() / manifest.key).exists():
                raise CloudPluginError("Eingebaute Cloud-Plugins können nicht überschrieben werden")
            package = CloudPluginPackage(manifest=manifest, path=staging, builtin=False)
            load_plugin_module(package)
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
    return CloudPluginPackage(manifest=manifest, path=target, builtin=False)


def export_plugin_archive(package: CloudPluginPackage) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(package.path.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            bundle.write(path, path.relative_to(package.path).as_posix())
    return output.getvalue()


def remove_external_plugin(key: str, external_path: str) -> None:
    normalized = str(key).strip().lower()
    if not PLUGIN_KEY_PATTERN.fullmatch(normalized):
        raise CloudPluginError("Ungültiger Plugin-Schlüssel")
    if (builtin_plugins_path() / normalized).exists():
        raise CloudPluginError("Eingebaute Cloud-Plugins können nicht entfernt werden")
    target = Path(external_path) / normalized
    if not target.is_dir():
        raise CloudPluginError("Plugin ist nicht installiert")
    shutil.rmtree(target)


def _validated_members(bundle: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], str]:
    members = bundle.infolist()
    if not members or len(members) > MAX_FILES:
        raise CloudPluginError("Plugin-Archiv enthält zu viele oder keine Dateien")
    total_size = 0
    manifest_candidates: list[str] = []
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
            raise CloudPluginError("Plugin-Archiv enthält einen unsicheren Dateipfad")
        mode = member.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise CloudPluginError("Symbolische Links sind in Plugins nicht erlaubt")
        if not member.is_dir() and path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise CloudPluginError(f"Nicht erlaubter Dateityp: {path.suffix or member.filename}")
        total_size += member.file_size
        if total_size > MAX_EXTRACTED_BYTES:
            raise CloudPluginError("Entpacktes Plugin ist größer als 25 MB")
        if path.name == "manifest.json" and len(path.parts) <= 2:
            manifest_candidates.append(member.filename)
    if len(manifest_candidates) != 1:
        raise CloudPluginError("Plugin muss genau eine manifest.json im Hauptverzeichnis enthalten")
    manifest_path = PurePosixPath(manifest_candidates[0])
    prefix = f"{manifest_path.parts[0]}/" if len(manifest_path.parts) == 2 else ""
    for member in members:
        if prefix and not member.filename.startswith(prefix):
            raise CloudPluginError("Alle Plugin-Dateien müssen im selben Hauptverzeichnis liegen")
    return members, prefix


def _relative_name(filename: str, prefix: str) -> str:
    return filename[len(prefix):] if prefix else filename
