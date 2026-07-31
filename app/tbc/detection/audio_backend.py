from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .classes import canonical_audio_detection_key

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioDetection:
    label: str
    detection_key: str
    confidence: float


@dataclass(frozen=True)
class AudioModelMetadata:
    """Schema for a local-audio-AI model's companion .json file.

    A model is any ONNX classifier that takes a single window of raw mono PCM
    samples at `sample_rate` and returns one confidence score per class in
    `classes` (index -> AudioSet-style class name, matched against
    classes.AUDIOSET_LABEL_TO_DETECTION_KEY). This mirrors the video pipeline's
    ModelMetadata/default.json convention in onnx_backend.py/model_provisioning.py.
    """

    input_name: str
    output_name: str
    sample_rate: int
    window_samples: int
    classes: dict[int, str]

    @classmethod
    def load(cls, path: Path) -> "AudioModelMetadata":
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        classes = {int(index): str(label) for index, label in data["classes"].items()}
        return cls(
            input_name=data["input_name"],
            output_name=data["output_name"],
            sample_rate=int(data.get("sample_rate", 16000)),
            window_samples=int(data.get("window_samples", 15360)),
            classes=classes,
        )


def decode_audio_output(
    scores: np.ndarray,
    metadata: AudioModelMetadata,
    *,
    confidence_threshold: float,
) -> list[AudioDetection]:
    """Decode a flat per-class confidence vector into AudioDetections.

    Several AudioSet-style labels can map to the same detection_key (e.g. "Dog",
    "Bark", and "Bow-wow" all mean "ai_bark") - the highest-confidence label above
    threshold for each detection_key wins, so the same bark isn't reported twice.
    """
    scores = np.asarray(scores).reshape(-1)
    best_by_key: dict[str, AudioDetection] = {}
    for index, confidence in enumerate(scores):
        if confidence < confidence_threshold:
            continue
        label = metadata.classes.get(index)
        if label is None:
            continue
        detection_key = canonical_audio_detection_key(label)
        if detection_key is None:
            continue
        existing = best_by_key.get(detection_key)
        if existing is not None and existing.confidence >= confidence:
            continue
        best_by_key[detection_key] = AudioDetection(
            label=label, detection_key=detection_key, confidence=float(confidence)
        )
    return list(best_by_key.values())


class AudioDetectionBackend(ABC):
    key: str = "audio_backend"

    @classmethod
    def available(cls) -> tuple[bool, str]:
        return False, "nicht implementiert"

    @abstractmethod
    def infer(self, waveform: np.ndarray) -> list[AudioDetection]:
        raise NotImplementedError


class OnnxAudioBackend(AudioDetectionBackend):
    key = "onnx_cpu_audio"
    providers: tuple[str, ...] = ("CPUExecutionProvider",)

    def __init__(self, model_path: str, metadata_path: str, *, confidence_threshold: float = 0.5) -> None:
        self.model_path = Path(model_path)
        self.metadata = AudioModelMetadata.load(Path(metadata_path))
        self.confidence_threshold = confidence_threshold
        self._session: Any = None

    @classmethod
    def available(cls) -> tuple[bool, str]:
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            return False, "onnxruntime ist nicht installiert"
        return True, "CPU audio inference available"

    def load(self) -> None:
        if self._session is not None:
            return
        import onnxruntime

        self._session = onnxruntime.InferenceSession(str(self.model_path), providers=list(self.providers))

    def infer(self, waveform: np.ndarray) -> list[AudioDetection]:
        self.load()
        assert self._session is not None
        tensor = np.expand_dims(np.asarray(waveform, dtype=np.float32), axis=0)
        raw_outputs = self._session.run([self.metadata.output_name], {self.metadata.input_name: tensor})
        return decode_audio_output(raw_outputs[0], self.metadata, confidence_threshold=self.confidence_threshold)
