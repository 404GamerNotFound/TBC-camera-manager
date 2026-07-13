from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path

LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL_URL = (
    "https://github.com/onnx/models/raw/main/validated/vision/"
    "object_detection_segmentation/ssd-mobilenetv1/model/ssd_mobilenet_v1_10.onnx"
)

# TF Object Detection API COCO label indices, restricted to the classes TBC maps to a
# canonical detection key (see classes.COCO_LABEL_TO_DETECTION_KEY).
DEFAULT_MODEL_METADATA: dict[str, object] = {
    "input_name": "image_tensor:0",
    "input_size": [300, 300],
    "input_dtype": "uint8",
    "output_boxes": "detection_boxes:0",
    "output_scores": "detection_scores:0",
    "output_classes": "detection_classes:0",
    "output_num": "num_detections:0",
    "classes": {
        "1": "person",
        "2": "bicycle",
        "3": "car",
        "4": "motorcycle",
        "6": "bus",
        "7": "train",
        "8": "truck",
        "16": "bird",
        "17": "cat",
        "18": "dog",
        "19": "horse",
        "20": "sheep",
        "21": "cow",
        "22": "elephant",
        "23": "bear",
        "24": "zebra",
        "25": "giraffe",
    },
}


def ensure_default_model(model_path: Path, metadata_path: Path) -> bool:
    """Provisions the bundled default ONNX model on first start.

    The model binary is not committed to the repository; it is downloaded once into the
    TBC_DETECTION_MODEL_PATH volume. A failed download is logged and does not crash
    startup - cameras with local detection enabled simply keep retrying (see
    detection.supervisor.run_camera_detection_worker).
    """
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    if not metadata_path.exists():
        metadata_path.write_text(json.dumps(DEFAULT_MODEL_METADATA, ensure_ascii=False, indent=2), encoding="utf-8")
    if model_path.exists() and model_path.stat().st_size > 0:
        return True
    try:
        LOGGER.info("Lade Standard-Erkennungsmodell herunter: %s", DEFAULT_MODEL_URL)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(DEFAULT_MODEL_URL, model_path)  # noqa: S310
        return True
    except OSError as exc:
        LOGGER.warning("Standard-Erkennungsmodell konnte nicht geladen werden: %s", exc)
        return False
