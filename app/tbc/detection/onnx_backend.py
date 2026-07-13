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
class ModelMetadata:
    input_name: str
    input_size: tuple[int, int]
    input_dtype: str
    output_boxes: str
    output_scores: str
    output_classes: str
    output_num: str | None
    classes: dict[int, str]

    @classmethod
    def load(cls, path: Path) -> "ModelMetadata":
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        classes = {int(index): str(label) for index, label in data["classes"].items()}
        width, height = data["input_size"]
        return cls(
            input_name=data["input_name"],
            input_size=(int(width), int(height)),
            input_dtype=data.get("input_dtype", "uint8"),
            output_boxes=data["output_boxes"],
            output_scores=data["output_scores"],
            output_classes=data["output_classes"],
            output_num=data.get("output_num"),
            classes=classes,
        )


def preprocess_frame(frame: np.ndarray, metadata: ModelMetadata) -> np.ndarray:
    """frame: HxWx3 uint8 in BGR order (ffmpeg rawvideo output). Returns a batched NHWC tensor."""
    width, height = metadata.input_size
    image = Image.fromarray(frame[:, :, ::-1])
    image = image.resize((width, height), Image.BILINEAR)
    array = np.asarray(image)
    if metadata.input_dtype == "float32":
        array = array.astype(np.float32) / 255.0
    else:
        array = array.astype(np.uint8)
    return np.expand_dims(array, axis=0)


def decode_detection_output(
    outputs: dict[str, np.ndarray],
    metadata: ModelMetadata,
    *,
    confidence_threshold: float,
) -> list[Detection]:
    """Decode a TF-Object-Detection-API-style ONNX export: post-NMS boxes/scores/classes."""
    boxes = np.asarray(outputs[metadata.output_boxes])
    scores = np.asarray(outputs[metadata.output_scores])
    classes = np.asarray(outputs[metadata.output_classes])
    if boxes.ndim == 3:
        boxes = boxes[0]
    if scores.ndim == 2:
        scores = scores[0]
    if classes.ndim == 2:
        classes = classes[0]

    count = boxes.shape[0]
    if metadata.output_num is not None and metadata.output_num in outputs:
        reported = np.asarray(outputs[metadata.output_num]).reshape(-1)
        if reported.size:
            count = min(count, int(reported[0]))

    detections: list[Detection] = []
    for index in range(count):
        confidence = float(scores[index])
        if confidence < confidence_threshold:
            continue
        class_index = int(round(float(classes[index])))
        label = metadata.classes.get(class_index)
        if label is None:
            continue
        detection_key = canonical_detection_key(label)
        if detection_key is None:
            continue
        ymin, xmin, ymax, xmax = (float(value) for value in boxes[index][:4])
        box = (
            max(0.0, min(1.0, xmin)),
            max(0.0, min(1.0, ymin)),
            max(0.0, min(1.0, xmax)),
            max(0.0, min(1.0, ymax)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        detections.append(Detection(label=label, detection_key=detection_key, confidence=confidence, box=box))
    return detections


class OnnxCpuBackend(DetectionBackend):
    key = "onnx_cpu"

    def __init__(self, model_path: str, metadata_path: str, *, confidence_threshold: float = 0.5) -> None:
        self.model_path = Path(model_path)
        self.metadata = ModelMetadata.load(Path(metadata_path))
        self.confidence_threshold = confidence_threshold
        self._session: Any = None

    @classmethod
    def available(cls) -> tuple[bool, str]:
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            return False, "onnxruntime ist nicht installiert"
        return True, "CPU-Inferenz verfügbar"

    def load(self) -> None:
        if self._session is not None:
            return
        import onnxruntime

        self._session = onnxruntime.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])

    def infer(self, frame: np.ndarray) -> list[Detection]:
        self.load()
        assert self._session is not None
        tensor = preprocess_frame(frame, self.metadata)
        raw_outputs = self._session.run(None, {self.metadata.input_name: tensor})
        output_names = [output.name for output in self._session.get_outputs()]
        named_outputs = dict(zip(output_names, raw_outputs))
        return decode_detection_output(named_outputs, self.metadata, confidence_threshold=self.confidence_threshold)
