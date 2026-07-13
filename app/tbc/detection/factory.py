from __future__ import annotations

from typing import Any

from .backend import DetectionBackend
from .onnx_backend import OnnxCpuBackend

BACKEND_CHOICES: tuple[str, ...] = ("cpu",)


def build_backend(settings: dict[str, Any], *, model_path: str, metadata_path: str) -> DetectionBackend:
    confidence_threshold = float(settings.get("confidence_threshold") or 0.5)
    return OnnxCpuBackend(model_path, metadata_path, confidence_threshold=confidence_threshold)


def backend_status() -> list[tuple[str, bool, str]]:
    available, message = OnnxCpuBackend.available()
    return [("cpu", available, message)]
