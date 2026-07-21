from __future__ import annotations

from typing import Any

from .audio_backend import AudioDetectionBackend, OnnxAudioBackend


def build_backend(settings: dict[str, Any], *, model_path: str, metadata_path: str) -> AudioDetectionBackend:
    confidence_threshold = float(settings.get("confidence_threshold") or 0.5)
    return OnnxAudioBackend(model_path, metadata_path, confidence_threshold=confidence_threshold)


def backend_status() -> tuple[str, bool, str]:
    return ("onnx_cpu_audio", *OnnxAudioBackend.available())
