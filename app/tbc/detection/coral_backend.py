from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .backend import Detection, DetectionBackend
from .classes import canonical_detection_key

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoralModelMetadata:
    """Metadata for a Coral Edge TPU model.

    Deliberately smaller than onnx_backend.ModelMetadata: pycoral's detect.get_objects()
    already decodes boxes/scores/classes for a "*_edgetpu.tflite" model with a built-in
    TFLite_Detection_PostProcess op, so there is no output-tensor-name mapping to
    configure here - only the input size and the model's own class-index -> COCO-style
    label mapping (reused by classes.canonical_detection_key, same as the ONNX path).
    """

    input_size: tuple[int, int]
    classes: dict[int, str]

    @classmethod
    def load(cls, path: Path) -> "CoralModelMetadata":
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        classes = {int(index): str(label) for index, label in data["classes"].items()}
        width, height = data["input_size"]
        return cls(input_size=(int(width), int(height)), classes=classes)


class CoralEdgeTpuBackend(DetectionBackend):
    """Runs a TensorFlow-Lite model compiled for the Coral Edge TPU, via pycoral.

    Needs a different model file (an edgetpu-compiled .tflite, not .onnx) and the
    pycoral/tflite-runtime packages, neither of which TBC installs by default (see
    Dockerfile.coral). Written against pycoral's stable, long-documented high-level API
    (make_interpreter/list_edge_tpus/common.set_input/detect.get_objects) but has not
    been run against real Edge TPU hardware in TBC's own development environment - there
    is none available there. Verify on your own device before relying on it in production.
    """

    key = "coral_edgetpu"

    def __init__(self, model_path: str, metadata_path: str, *, confidence_threshold: float = 0.5) -> None:
        self.model_path = Path(model_path)
        self.metadata = CoralModelMetadata.load(Path(metadata_path))
        self.confidence_threshold = confidence_threshold
        self._interpreter: Any = None

    @classmethod
    def available(cls) -> tuple[bool, str]:
        try:
            from pycoral.utils.edgetpu import list_edge_tpus
        except ImportError:
            return False, "pycoral/tflite-runtime ist nicht installiert"
        try:
            tpus = list_edge_tpus()
        except Exception as exc:
            return False, f"Edge-TPU-Laufzeit konnte nicht abgefragt werden: {exc}"
        if not tpus:
            return False, "Kein Coral Edge-TPU-Gerät gefunden"
        return True, f"{len(tpus)} Edge-TPU-Gerät(e) gefunden"

    def load(self) -> None:
        if self._interpreter is not None:
            return
        from pycoral.utils.edgetpu import make_interpreter

        self._interpreter = make_interpreter(str(self.model_path))
        self._interpreter.allocate_tensors()

    def infer(self, frame: np.ndarray) -> list[Detection]:
        self.load()
        from pycoral.adapters import common, detect

        width, height = self.metadata.input_size
        image = Image.fromarray(frame[:, :, ::-1]).resize((width, height), Image.BILINEAR)
        common.set_input(self._interpreter, np.asarray(image))
        self._interpreter.invoke()
        objects = detect.get_objects(self._interpreter, score_threshold=self.confidence_threshold)
        return self._to_detections(objects, width, height)

    def _to_detections(self, objects: list[Any], width: int, height: int) -> list[Detection]:
        detections: list[Detection] = []
        for obj in objects:
            label = self.metadata.classes.get(obj.id)
            if label is None:
                continue
            detection_key = canonical_detection_key(label)
            if detection_key is None:
                continue
            box = (
                max(0.0, min(1.0, obj.bbox.xmin / width)),
                max(0.0, min(1.0, obj.bbox.ymin / height)),
                max(0.0, min(1.0, obj.bbox.xmax / width)),
                max(0.0, min(1.0, obj.bbox.ymax / height)),
            )
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            detections.append(Detection(label=label, detection_key=detection_key, confidence=float(obj.score), box=box))
        return detections
