from __future__ import annotations

from typing import Any

from .backend import DetectionBackend
from .coral_backend import CoralEdgeTpuBackend
from .onnx_backend import OnnxCpuBackend, OnnxGpuBackend

BACKEND_CHOICES: tuple[str, ...] = ("cpu", "cuda", "coral")

BACKEND_LABELS: dict[str, str] = {
    "cpu": "CPU",
    "cuda": "GPU (CUDA)",
    "coral": "Coral (Edge TPU)",
}

_BACKEND_CLASSES: dict[str, type[DetectionBackend]] = {
    "cpu": OnnxCpuBackend,
    "cuda": OnnxGpuBackend,
    "coral": CoralEdgeTpuBackend,
}


def build_backend(settings: dict[str, Any], *, model_path: str, metadata_path: str) -> DetectionBackend:
    confidence_threshold = float(settings.get("confidence_threshold") or 0.5)
    backend_key = str(settings.get("backend") or "cpu").strip().lower()
    backend_cls = _BACKEND_CLASSES.get(backend_key, OnnxCpuBackend)
    return backend_cls(model_path, metadata_path, confidence_threshold=confidence_threshold)


def backend_status() -> list[tuple[str, bool, str]]:
    return [(key, *backend_cls.available()) for key, backend_cls in _BACKEND_CLASSES.items()]
