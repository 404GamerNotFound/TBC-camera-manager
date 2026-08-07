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

# AudioSet class names (from the pretrained audio classifier) that map to each
# local-audio-AI trigger key. Several AudioSet labels can map to the same key -
# e.g. a smoke alarm and a generic beeping fire alarm should both raise
# "ai_smoke_alarm". Prefixed with "ai_" for the same reason as the vision keys
# above, and additionally kept distinct from the vendor-reported "sound"/"cry"
# detection_key tokens (see camera_modules/detections.py's DIRECT_TOKEN_MAP) -
# those describe a camera's own onboard audio-event flag, not TBC's own local
# audio-classification pipeline.
AUDIOSET_LABEL_TO_DETECTION_KEY: dict[str, str] = {
    "dog": "ai_bark",
    "bark": "ai_bark",
    "bow-wow": "ai_bark",
    "howl": "ai_bark",
    "growling": "ai_bark",
    "glass": "ai_glass_break",
    "shatter": "ai_glass_break",
    "smoke detector, smoke alarm": "ai_smoke_alarm",
    "fire alarm": "ai_smoke_alarm",
    "smoke alarm": "ai_smoke_alarm",
}

AUDIO_KEY_LABELS: dict[str, str] = {
    "ai_bark": "Hund bellt (lokale KI)",
    "ai_glass_break": "Glasbruch (lokale KI)",
    "ai_smoke_alarm": "Rauchmelder (lokale KI)",
}

# Momentary trigger keys for a "line" zone crossing, one pair per class/direction. Separate from
# LOITERING_KEY_LABELS above (a continuous "still present" state) - these fire briefly once per
# crossing, like a doorbell press rather than a held switch.
LINE_CROSSING_KEY_LABELS: dict[str, str] = {
    "ai_person_line_in": "Person kreuzt Linie rein (lokale KI)",
    "ai_person_line_out": "Person kreuzt Linie raus (lokale KI)",
    "ai_vehicle_line_in": "Fahrzeug kreuzt Linie rein (lokale KI)",
    "ai_vehicle_line_out": "Fahrzeug kreuzt Linie raus (lokale KI)",
    "ai_animal_line_in": "Tier kreuzt Linie rein (lokale KI)",
    "ai_animal_line_out": "Tier kreuzt Linie raus (lokale KI)",
}


def canonical_detection_key(label: str) -> str | None:
    return COCO_LABEL_TO_DETECTION_KEY.get(label.strip().lower())


def canonical_audio_detection_key(label: str) -> str | None:
    return AUDIOSET_LABEL_TO_DETECTION_KEY.get(label.strip().lower())


def loitering_key_for(detection_key: str) -> str | None:
    return f"{detection_key}_loitering" if detection_key in DETECTION_KEY_LABELS else None


def line_crossing_key_for(detection_key: str, direction: str) -> str | None:
    if direction not in ("in", "out") or detection_key not in DETECTION_KEY_LABELS:
        return None
    return f"{detection_key}_line_{direction}"
