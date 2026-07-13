from __future__ import annotations

COCO_LABEL_TO_DETECTION_KEY: dict[str, str] = {
    "person": "person",
    "bicycle": "vehicle",
    "car": "vehicle",
    "motorcycle": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle",
    "train": "vehicle",
    "bird": "animal",
    "cat": "animal",
    "dog": "animal",
    "horse": "animal",
    "sheep": "animal",
    "cow": "animal",
    "elephant": "animal",
    "bear": "animal",
    "zebra": "animal",
    "giraffe": "animal",
}

DETECTION_KEY_LABELS: dict[str, str] = {
    "person": "Person",
    "vehicle": "Fahrzeug",
    "animal": "Tier",
}


def canonical_detection_key(label: str) -> str | None:
    return COCO_LABEL_TO_DETECTION_KEY.get(label.strip().lower())
