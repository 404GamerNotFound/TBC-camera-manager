from __future__ import annotations

COCO_LABEL_TO_DETECTION_KEY: dict[str, str] = {
    "person": "ai_person",
    "bicycle": "ai_vehicle",
    "car": "ai_vehicle",
    "motorcycle": "ai_vehicle",
    "bus": "ai_vehicle",
    "truck": "ai_vehicle",
    "train": "ai_vehicle",
    "bird": "ai_animal",
    "cat": "ai_animal",
    "dog": "ai_animal",
    "horse": "ai_animal",
    "sheep": "ai_animal",
    "cow": "ai_animal",
    "elephant": "ai_animal",
    "bear": "ai_animal",
    "zebra": "ai_animal",
    "giraffe": "ai_animal",
}

# Prefixed so these never collide with a vendor module's own detection_key
# (e.g. Reolink's native "person"/"vehicle"/"animal"), which would otherwise make
# a single trigger checkbox ambiguously control both a camera-native and a
# TBC-local detection source at once.
DETECTION_KEY_LABELS: dict[str, str] = {
    "ai_person": "Person (lokale KI)",
    "ai_vehicle": "Fahrzeug (lokale KI)",
    "ai_animal": "Tier (lokale KI)",
}


def canonical_detection_key(label: str) -> str | None:
    return COCO_LABEL_TO_DETECTION_KEY.get(label.strip().lower())
