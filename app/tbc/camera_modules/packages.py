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

from .base import ArchiveDownload, CameraCapability, CameraModule, CameraSnapshot, ModuleFeatureUnsupported
from ..plugin_requirements import MissingPluginRequirements, missing_requirements, read_requirements_field

PLUGIN_SCHEMA_VERSION = 1
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_BYTES = 25 * 1024 * 1024
MAX_FILES = 200
PLUGIN_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
ALLOWED_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".txt"}
# Extensionless files with none of the suffixes above still pass validation
# when their bare name is one of these - lets a plugin ship its own LICENSE
# file, which the /license page then surfaces automatically (see licenses.py).
ALLOWED_BARE_FILENAMES = {"LICENSE", "COPYING", "NOTICE"}


class CameraPluginError(ValueError):
    pass


@dataclass(frozen=True)
class PluginManifest:
    schema_version: int
    key: str
    label: str
    version: str
    description: str
    entrypoint: str
    capabilities: frozenset[CameraCapability]
    default_onvif_port: int
    default_http_port: int
    default_rtsp_port: int
    requirements: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginPackage:
    manifest: PluginManifest
    path: Path
    builtin: bool


def builtin_plugins_path() -> Path:
    return Path(__file__).resolve().parents[1] / "camera_plugins"


def discover_plugin_packages(external_path: str) -> tuple[PluginPackage, ...]:
    packages: list[PluginPackage] = []
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
            packages.append(PluginPackage(manifest=manifest, path=path, builtin=builtin))
            seen.add(manifest.key)
    return tuple(packages)


def read_manifest(path: Path) -> PluginManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CameraPluginError(f"Manifest konnte nicht gelesen werden: {exc}") from exc
    if not isinstance(raw, dict):
        raise CameraPluginError("manifest.json must contain a JSON object")
    try:
        schema_version = int(raw.get("schema_version") or 0)
    except (TypeError, ValueError) as exc:
        raise CameraPluginError("The plugin schema version must be a number") from exc
    if schema_version != PLUGIN_SCHEMA_VERSION:
        raise CameraPluginError(f"Unsupported plugin schema version: {schema_version}")
    key = str(raw.get("key") or "").strip().lower()
    if not PLUGIN_KEY_PATTERN.fullmatch(key):
        raise CameraPluginError("Invalid plugin key")
    label = str(raw.get("label") or "").strip()
    version = str(raw.get("version") or "").strip()
    if not label or not version:
        raise CameraPluginError("Plugin name and version are required")
    entrypoint = str(raw.get("entrypoint") or "plugin.py").strip()
    entrypoint_path = PurePosixPath(entrypoint)
    if (
        entrypoint_path.is_absolute()
        or ".." in entrypoint_path.parts
        or len(entrypoint_path.parts) != 1
        or entrypoint_path.suffix != ".py"
    ):
        raise CameraPluginError("Invalid plugin entry point")
    capability_values = raw.get("capabilities", [])
    if not isinstance(capability_values, list):
        raise CameraPluginError("capabilities must be a JSON list")
    try:
        capabilities = frozenset(CameraCapability(str(value)) for value in capability_values)
    except ValueError as exc:
        raise CameraPluginError(f"Unknown plugin capability: {exc}") from exc
    ports = raw.get("ports") or {}
    if not isinstance(ports, dict):
        raise CameraPluginError("ports must be a JSON object")
    try:
        requirements = read_requirements_field(raw.get("requirements"))
    except ValueError as exc:
        raise CameraPluginError(str(exc)) from exc
    return PluginManifest(
        schema_version=schema_version,
        key=key,
        label=label,
        version=version,
        description=str(raw.get("description") or "").strip(),
        entrypoint=entrypoint,
        capabilities=capabilities,
        default_onvif_port=_valid_port(ports.get("onvif"), 8000),
        default_http_port=_valid_port(ports.get("http"), 80),
        default_rtsp_port=_valid_port(ports.get("rtsp"), 554),
        requirements=requirements,
    )


def load_plugin_module(package: PluginPackage) -> CameraModule:
    entrypoint = package.path / package.manifest.entrypoint
    if not entrypoint.is_file():
        raise CameraPluginError(f"Plugin-Einstiegspunkt fehlt: {package.manifest.entrypoint}")
    import_name = f"tbc_camera_plugin_{package.manifest.key}"
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
        raise CameraPluginError("The plugin entry point could not be loaded")
    imported = importlib.util.module_from_spec(spec)
    sys.modules[import_name] = imported
    try:
        spec.loader.exec_module(imported)
        factory = getattr(imported, "create_module", None)
        module = factory() if callable(factory) else getattr(imported, "MODULE", None)
    except Exception as exc:
        sys.modules.pop(import_name, None)
        raise CameraPluginError(f"Plugin-Code konnte nicht geladen werden: {exc}") from exc
    if not isinstance(module, CameraModule):
        raise CameraPluginError("plugin.py must provide create_module() or MODULE with a CameraModule")
    manifest = package.manifest
    module.key = manifest.key
    module.label = manifest.label
    module.description = manifest.description
    module.capabilities = manifest.capabilities
    module.default_onvif_port = manifest.default_onvif_port
    module.default_http_port = manifest.default_http_port
    module.default_rtsp_port = manifest.default_rtsp_port
    return module


def _install_plugin_api() -> None:
    api = types.ModuleType("tbc_camera_api")
    api.ArchiveDownload = ArchiveDownload
    api.CameraCapability = CameraCapability
    api.CameraModule = CameraModule
    api.CameraSnapshot = CameraSnapshot
    api.ModuleFeatureUnsupported = ModuleFeatureUnsupported
    tbc_package = __package__.rsplit(".camera_modules", 1)[0]
    api.import_tbc = lambda module_path: importlib.import_module(f"{tbc_package}.{module_path}")
    # Shared, manufacturer-neutral building blocks (ONVIF probing/PTZ, stream URI
    # helpers, detection-key normalization, the manual-RTSP module base class):
    # plugins reach these through the api instead of relative imports so that a
    # plugin's own device-specific code never has to know its dotted location in
    # the host's package tree - see docs/camera-modules.md.
    api.onvif = importlib.import_module(f"{tbc_package}.camera_modules.onvif")
    api.onvif_control = importlib.import_module(f"{tbc_package}.camera_modules.onvif_control")
    api.streams = importlib.import_module(f"{tbc_package}.camera_modules.streams")
    api.detections = importlib.import_module(f"{tbc_package}.camera_modules.detections")
    api.ManualRtspCameraModule = importlib.import_module(f"{tbc_package}.manual_rtsp.module").ManualRtspCameraModule
    sys.modules["tbc_camera_api"] = api


def install_plugin_archive(archive: bytes, external_path: str) -> PluginPackage:
    if not archive or len(archive) > MAX_ARCHIVE_BYTES:
        raise CameraPluginError("The plugin file is empty or larger than 10 MB")
    root = Path(external_path)
    root.mkdir(parents=True, exist_ok=True)
    try:
        bundle = zipfile.ZipFile(BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise CameraPluginError("The plugin file is not a valid ZIP archive") from exc
    with bundle:
        members, prefix = _validated_members(bundle)
        manifest_member = next(member for member in members if _relative_name(member.filename, prefix) == "manifest.json")
        try:
            manifest_raw = bundle.read(manifest_member)
        except OSError as exc:
            raise CameraPluginError(f"Manifest konnte nicht gelesen werden: {exc}") from exc
        with tempfile.TemporaryDirectory(prefix=".camera-plugin-", dir=root) as temp_dir:
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
                raise CameraPluginError("Built-in plugins cannot be overwritten")
            missing = missing_requirements(manifest.requirements)
            if missing:
                raise MissingPluginRequirements(
                    missing, plugin_label=manifest.label, plugin_kind="camera", module_key=manifest.key
                )
            package = PluginPackage(manifest=manifest, path=staging, builtin=False)
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
    return PluginPackage(manifest=manifest, path=target, builtin=False)


def export_plugin_archive(package: PluginPackage) -> bytes:
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
        raise CameraPluginError("Invalid plugin key")
    if (builtin_plugins_path() / normalized).exists():
        raise CameraPluginError("Built-in plugins cannot be removed")
    target = Path(external_path) / normalized
    if not target.is_dir():
        raise CameraPluginError("The plugin is not installed")
    shutil.rmtree(target)


def _validated_members(bundle: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], str]:
    members = bundle.infolist()
    if not members or len(members) > MAX_FILES:
        raise CameraPluginError("The plugin archive contains too many files or no files")
    total_size = 0
    manifest_candidates: list[str] = []
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
            raise CameraPluginError("The plugin archive contains an unsafe file path")
        mode = member.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise CameraPluginError("Symbolic links are not allowed in plugins")
        if (
            not member.is_dir()
            and path.suffix.lower() not in ALLOWED_SUFFIXES
            and path.name not in ALLOWED_BARE_FILENAMES
        ):
            raise CameraPluginError(f"Nicht erlaubter Dateityp: {path.suffix or member.filename}")
        total_size += member.file_size
        if total_size > MAX_EXTRACTED_BYTES:
            raise CameraPluginError("The extracted plugin is larger than 25 MB")
        if path.name == "manifest.json" and len(path.parts) <= 2:
            manifest_candidates.append(member.filename)
    if len(manifest_candidates) != 1:
        raise CameraPluginError("The plugin must contain exactly one manifest.json in its root directory")
    manifest_path = PurePosixPath(manifest_candidates[0])
    prefix = f"{manifest_path.parts[0]}/" if len(manifest_path.parts) == 2 else ""
    for member in members:
        if prefix and not member.filename.startswith(prefix):
            raise CameraPluginError("All plugin files must be in the same root directory")
    return members, prefix


def _relative_name(filename: str, prefix: str) -> str:
    return filename[len(prefix):] if prefix else filename


def _valid_port(value: Any, fallback: int) -> int:
    try:
        port = int(value if value is not None else fallback)
    except (TypeError, ValueError) as exc:
        raise CameraPluginError("Port values must be numbers") from exc
    if not 1 <= port <= 65535:
        raise CameraPluginError("Port values must be between 1 and 65535")
    return port
