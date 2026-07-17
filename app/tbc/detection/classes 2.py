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

# Separate trigger keys for "present in a loiter zone for at least N seconds",
# distinct from the plain per-frame detection keys above so they can be recorded
# on (or filtered from) independently.
LOITERING_KEY_LABELS: dict[str, str] = {
    "ai_person_loitering": "Person verweilt (lokale KI)",
    "ai_vehicle_loitering": "Fahrzeug verweilt (lokale KI)",
    "ai_animal_loitering": "Tier verweilt (lokale KI)",
}


def canonical_detection_key(label: str) -> str | None:
    return COCO_LABEL_TO_DETECTION_KEY.get(label.strip().lower())


def loitering_key_for(detection_key: str) -> str | None:
    return f"{detection_key}_loitering" if detection_key in DETECTION_KEY_LABELS else None
