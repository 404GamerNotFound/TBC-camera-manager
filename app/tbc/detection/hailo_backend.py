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
class HailoModelMetadata:
    """Metadata for a Hailo-8/8L model (a compiled ``.hef`` file).

    Deliberately the same shape as coral_backend.CoralModelMetadata: a HEF compiled with
    on-chip NMS already decodes boxes/scores/classes itself (see
    decode_hailo_nms_output below), so there is nothing to configure here beyond the
    input size and the model's own class-index -> label mapping.
    """

    input_size: tuple[int, int]
    classes: dict[int, str]

    @classmethod
    def load(cls, path: Path) -> "HailoModelMetadata":
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        classes = {int(index): str(label) for index, label in data["classes"].items()}
        width, height = data["input_size"]
        return cls(input_size=(int(width), int(height)), classes=classes)


def decode_hailo_nms_output(raw_output: list[Any], metadata: HailoModelMetadata, *, confidence_threshold: float) -> list[Detection]:
    """Decodes a HailoRT on-chip NMS output buffer.

    ``ConfiguredInferModel.Bindings.InferStream.get_buffer()`` for an NMS-format
    detection output returns - per HailoRT's own pyhailort docstring - "a list of
    numpy.array where each array represents the detections for a specific class:
    [cls0_detections, cls1_detections, ...]. Each numpy.array shape is (number of
    detections, bounding box params) where the 2nd dimension (bounding box params) is
    of a fixed length of 5 (y_min, x_min, y_max, x_max, score)." (verified against
    hailo-ai/hailort's pyhailort.py bindings source and against the on-chip-NMS decode
    used by hailo-ai/hailo-apps's own object_detection example). Boxes are normalized
    0..1 in that fixed axis order - not the (xmin, ymin, xmax, ymax) order
    coral_backend.decode_edgetpu_detection_output uses for the Coral/TFLite contract.
    """
    detections: list[Detection] = []
    for class_index, class_detections in enumerate(raw_output):
        label = metadata.classes.get(class_index)
        if label is None:
            continue
        detection_key = canonical_detection_key(label)
        if detection_key is None:
            continue
        for row in class_detections:
            ymin, xmin, ymax, xmax, confidence = (float(value) for value in row[:5])
            if confidence < confidence_threshold:
                continue
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


class HailoBackend(DetectionBackend):
    """Runs a model compiled for the Hailo-8/8L neural accelerator via HailoRT.

    Needs the ``hailo_platform`` Python package (HailoRT's bindings, distributed by
    Hailo through their Developer Zone - there is no public PyPI wheel TBC can
    depend on directly, so it is not in requirements.txt) plus a connected Hailo
    device, neither of which TBC installs by default. Also needs a ``.hef`` model
    compiled with on-chip NMS for a single input and a single (NMS) output - the
    common shape for an object-detection HEF, e.g. from the public
    [Hailo Model Zoo](https://github.com/hailo-ai/hailo_model_zoo). There is no
    verified, stable public HEF download URL TBC can provision automatically (HEFs
    are compiled per Hailo device generation/DFC version), so - like the local-audio-AI
    model in model_provisioning.ensure_audio_model - the admin must supply
    ``default_hailo.hef`` and a matching ``default_hailo.json`` (metadata, see
    HailoModelMetadata) in the detection models directory themselves.

    This has not been run against real Hailo hardware in TBC's own development
    environment - there is none available there. The API calls below are verified
    against HailoRT's own pyhailort.py bindings and hailo-ai's official example code
    (VDevice/InferModel/ConfiguredInferModel), but treat this as a solid, buildable
    starting point and verify it on your own device before relying on it in
    production - the same caveat coral_backend.CoralEdgeTpuBackend ships with.
    """

    key = "hailo"

    def __init__(self, model_path: str, metadata_path: str, *, confidence_threshold: float = 0.5) -> None:
        self.model_path = str(model_path)
        self.metadata = HailoModelMetadata.load(Path(metadata_path))
        self.confidence_threshold = confidence_threshold
        self._vdevice: Any = None
        self._infer_model: Any = None
        self._config_ctx: Any = None
        self._configured_model: Any = None
        self._output_name: str | None = None

    @classmethod
    def available(cls) -> tuple[bool, str]:
        try:
            from hailo_platform import VDevice
        except ImportError:
            return False, "hailo_platform (HailoRT) ist nicht installiert"
        try:
            device = VDevice()
        except Exception as exc:  # noqa: BLE001 - any native init failure means "unavailable"
            return False, f"Hailo device could not be initialized: {exc}"
        device.release()
        return True, "Hailo device found"

    def load(self) -> None:
        if self._configured_model is not None:
            return
        from hailo_platform import VDevice

        self._vdevice = VDevice()
        self._infer_model = self._vdevice.create_infer_model(self.model_path)
        self._config_ctx = self._infer_model.configure()
        self._configured_model = self._config_ctx.__enter__()
        self._output_name = self._infer_model.output_names[0]

    def infer(self, frame: np.ndarray) -> list[Detection]:
        self.load()
        assert self._configured_model is not None
        assert self._infer_model is not None
        assert self._output_name is not None

        width, height = self.metadata.input_size
        image = Image.fromarray(frame[:, :, ::-1]).resize((width, height), Image.BILINEAR)
        input_buffer = np.ascontiguousarray(np.asarray(image, dtype=np.uint8))

        output_stream = self._infer_model.output(self._output_name)
        output_buffer = np.empty(output_stream.shape, dtype=np.float32)

        bindings = self._configured_model.create_bindings(output_buffers={self._output_name: output_buffer})
        bindings.input().set_buffer(input_buffer)
        self._configured_model.run([bindings], 5000)

        raw_output = bindings.output(self._output_name).get_buffer()
        return decode_hailo_nms_output(raw_output, self.metadata, confidence_threshold=self.confidence_threshold)
