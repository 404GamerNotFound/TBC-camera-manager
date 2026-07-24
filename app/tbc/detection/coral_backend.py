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

    Deliberately smaller than onnx_backend.ModelMetadata: a "*_edgetpu.tflite"
    model's built-in TFLite_Detection_PostProcess op already decodes
    boxes/scores/classes in a fixed output-tensor order (see
    decode_edgetpu_detection_output below), so there is no output-tensor-name
    mapping to configure here - only the input size and the model's own
    class-index -> COCO-style label mapping (reused by
    classes.canonical_detection_key, same as the ONNX path).
    """

    input_size: tuple[int, int]
    classes: dict[int, str]

    @classmethod
    def load(cls, path: Path) -> "CoralModelMetadata":
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        classes = {int(index): str(label) for index, label in data["classes"].items()}
        width, height = data["input_size"]
        return cls(input_size=(int(width), int(height)), classes=classes)


def decode_edgetpu_detection_output(
    boxes: np.ndarray,
    classes: np.ndarray,
    scores: np.ndarray,
    count: int,
    metadata: CoralModelMetadata,
    *,
    confidence_threshold: float,
) -> list[Detection]:
    """Decode a TFLite_Detection_PostProcess op's four output tensors.

    Every Coral-compiled SSD detection model (including the
    default_edgetpu.tflite this app downloads - see model_provisioning.py)
    embeds this op, which always produces its results in this fixed tensor
    order: boxes [N, 4] as (ymin, xmin, ymax, xmax) already normalized to
    0..1, classes [N], scores [N], and a scalar detection count. This is a
    stable, documented TFLite contract - not something reverse-engineered
    from pycoral, which is not used here at all (see CoralEdgeTpuBackend's
    docstring for why).
    """
    detections: list[Detection] = []
    for index in range(min(int(count), boxes.shape[0])):
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


def _import_interpreter_api() -> tuple[Any, Any]:
    """Returns (Interpreter, load_delegate) from whichever TFLite runtime is
    installed - ai-edge-litert if present, else tflite-runtime.

    Neither Google's "pycoral" nor "tflite-runtime" package ever shipped a
    Linux wheel past Python 3.9 (both package indexes top out at cp39 for
    linux_x86_64/aarch64 - verified directly against
    https://google-coral.github.io/py-repo/ - a cp310 entry tflite-runtime's
    own index page lists turns out to be macOS-only), while this project's
    other pinned dependencies (fastapi included) require Python >=3.10. There
    is no single Python version that satisfies both, so this backend never
    imports pycoral or tflite-runtime directly. ai-edge-litert is Google's
    actual maintained successor - same Interpreter/load_delegate API, real
    Python 3.10-3.14 Linux wheels on regular PyPI - see Dockerfile.coral for
    the resulting base image choice. tflite_runtime stays as a fallback import
    purely for anyone who already has an environment built around it (e.g. an
    older Coral setup outside this project's own Dockerfile.coral).
    """
    try:
        from ai_edge_litert.interpreter import Interpreter, load_delegate

        return Interpreter, load_delegate
    except ImportError:
        pass
    from tflite_runtime.interpreter import Interpreter, load_delegate

    return Interpreter, load_delegate


class CoralEdgeTpuBackend(DetectionBackend):
    """Runs a TensorFlow-Lite model compiled for the Coral Edge TPU.

    Uses ai-edge-litert's (or tflite-runtime's) own Interpreter plus the
    libedgetpu delegate directly, NOT the pycoral convenience package - see
    _import_interpreter_api's docstring for why.

    Needs a different model file (an edgetpu-compiled .tflite, not .onnx) and
    ai-edge-litert plus the libedgetpu native runtime, neither of which TBC
    installs by default (see Dockerfile.coral). This has not been run against
    real Edge TPU hardware in TBC's own development environment - there is
    none available there. Verify on your own device before relying on it in
    production.
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
            _interpreter_cls, load_delegate = _import_interpreter_api()
        except ImportError:
            return False, "ai-edge-litert/tflite-runtime is not installed"
        try:
            load_delegate("libedgetpu.so.1")
        except (OSError, ValueError) as exc:
            return False, f"Edge TPU runtime/device could not be initialized: {exc}"
        return True, "Edge TPU device found"

    def load(self) -> None:
        if self._interpreter is not None:
            return
        interpreter_cls, load_delegate = _import_interpreter_api()
        delegate = load_delegate("libedgetpu.so.1")
        self._interpreter = interpreter_cls(model_path=str(self.model_path), experimental_delegates=[delegate])
        self._interpreter.allocate_tensors()

    def infer(self, frame: np.ndarray) -> list[Detection]:
        self.load()
        assert self._interpreter is not None
        width, height = self.metadata.input_size
        image = Image.fromarray(frame[:, :, ::-1]).resize((width, height), Image.BILINEAR)
        input_details = self._interpreter.get_input_details()
        input_data = np.expand_dims(np.asarray(image, dtype=np.uint8), axis=0)
        self._interpreter.set_tensor(input_details[0]["index"], input_data)
        self._interpreter.invoke()
        output_details = self._interpreter.get_output_details()
        boxes = self._interpreter.get_tensor(output_details[0]["index"])[0]
        classes = self._interpreter.get_tensor(output_details[1]["index"])[0]
        scores = self._interpreter.get_tensor(output_details[2]["index"])[0]
        count = self._interpreter.get_tensor(output_details[3]["index"])[0]
        return decode_edgetpu_detection_output(
            boxes, classes, scores, count, self.metadata, confidence_threshold=self.confidence_threshold
        )
