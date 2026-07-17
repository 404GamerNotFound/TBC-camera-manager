from __future__ import annotations

import json
import logging
from pathlib import Path

from ..camera_modules.registry import list_camera_module_registrations
from .model_provisioning import download_model_if_missing

LOGGER = logging.getLogger(__name__)

PLUGIN_MODEL_METADATA_FILENAME = "detection_model.json"


def resolve_plugin_model(module_key: str | None, *, cache_root: Path) -> tuple[Path, Path] | None:
    """Looks up whether a camera's assigned module ships its own detection model.

    A camera module opts in by placing a detection_model.json file next to its own
    manifest.json - the same schema as the app's built-in default metadata (see
    onnx_backend.ModelMetadata), plus a "model_url" the binary is downloaded from. When
    present, this is preferred over the app-wide default model for any camera using that
    module. Returns None (fall back to the default model) if the module has no package
    on disk (e.g. an entry-point-installed module) or ships no such file.
    """
    if not module_key:
        return None
    package_path = _plugin_package_path(module_key)
    if package_path is None:
        return None
    metadata_source = package_path / PLUGIN_MODEL_METADATA_FILENAME
    if not metadata_source.is_file():
        return None
    try:
        raw_metadata = metadata_source.read_text(encoding="utf-8")
        metadata = json.loads(raw_metadata)
    except (OSError, ValueError):
        LOGGER.warning("Ungültige %s für Kamera-Modul %s", PLUGIN_MODEL_METADATA_FILENAME, module_key)
        return None
    model_url = metadata.get("model_url")
    if not model_url:
        LOGGER.warning("%s für Kamera-Modul %s hat keine model_url", PLUGIN_MODEL_METADATA_FILENAME, module_key)
        return None

    cache_dir = cache_root / "plugins" / str(module_key).strip().lower()
    cache_dir.mkdir(parents=True, exist_ok=True)
    model_path = cache_dir / "model.onnx"
    metadata_path = cache_dir / "model.json"
    if not metadata_path.exists() or metadata_path.read_text(encoding="utf-8") != raw_metadata:
        metadata_path.write_text(raw_metadata, encoding="utf-8")
        # The plugin's model_url may have changed (e.g. a plugin update) - drop any
        # previously cached binary so the new one gets downloaded below.
        model_path.unlink(missing_ok=True)
    if not download_model_if_missing(model_url, model_path):
        return None
    return model_path, metadata_path


def _plugin_package_path(module_key: str) -> Path | None:
    normalized = str(module_key).strip().lower()
    for registration in list_camera_module_registrations():
        if str(registration.module.key).strip().lower() == normalized and registration.package is not None:
            return registration.package.path
    return None
