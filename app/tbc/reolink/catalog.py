from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class DetectionDefinition:
    key: str
    label: str
    category: str
    object_type: str | None = None
    capability_key: str | None = None
    smart_type: str | None = None
    smart_object: str | None = None


BASE_DETECTIONS: tuple[DetectionDefinition, ...] = (
    DetectionDefinition("motion", "Bewegung", "Basis", capability_key="motion_detection"),
    DetectionDefinition("face", "Gesicht", "KI-Objekte", object_type="face"),
    DetectionDefinition("person", "Person", "KI-Objekte", object_type="person"),
    DetectionDefinition("vehicle", "Fahrzeug", "KI-Objekte", object_type="vehicle"),
    DetectionDefinition(
        "non_motor_vehicle",
        "Nicht-motorisiertes Fahrzeug",
        "KI-Objekte",
        object_type="non-motor vehicle",
        capability_key="ai_non-motor vehicle",
    ),
    DetectionDefinition("pet", "Haustier", "KI-Objekte", object_type="pet"),
    DetectionDefinition("animal", "Tier", "KI-Objekte", object_type="pet", capability_key="ai_animal"),
    DetectionDefinition("package", "Paket", "KI-Objekte", object_type="package"),
    DetectionDefinition("visitor", "Besucher / Klingel", "Türklingel", object_type="visitor"),
    DetectionDefinition("cry", "Weinen", "Audio", object_type="cry"),
    DetectionDefinition("sleep", "Ruhezustand", "Diagnose", capability_key="sleep"),
    DetectionDefinition("io_input", "I/O Eingang", "I/O", capability_key="io_input"),
)

SMART_AI_DETECTIONS: tuple[DetectionDefinition, ...] = (
    DetectionDefinition("crossline_person", "Linienübertritt Person", "Smart-AI-Zonen", smart_type="crossline", smart_object="people"),
    DetectionDefinition("crossline_vehicle", "Linienübertritt Fahrzeug", "Smart-AI-Zonen", smart_type="crossline", smart_object="vehicle"),
    DetectionDefinition("crossline_dog_cat", "Linienübertritt Hund/Katze", "Smart-AI-Zonen", smart_type="crossline", smart_object="dog_cat"),
    DetectionDefinition("intrusion_person", "Eindringen Person", "Smart-AI-Zonen", smart_type="intrusion", smart_object="people"),
    DetectionDefinition("intrusion_vehicle", "Eindringen Fahrzeug", "Smart-AI-Zonen", smart_type="intrusion", smart_object="vehicle"),
    DetectionDefinition("intrusion_dog_cat", "Eindringen Hund/Katze", "Smart-AI-Zonen", smart_type="intrusion", smart_object="dog_cat"),
    DetectionDefinition("linger_person", "Verweilen Person", "Smart-AI-Zonen", smart_type="loitering", smart_object="people"),
    DetectionDefinition("linger_vehicle", "Verweilen Fahrzeug", "Smart-AI-Zonen", smart_type="loitering", smart_object="vehicle"),
    DetectionDefinition("linger_dog_cat", "Verweilen Hund/Katze", "Smart-AI-Zonen", smart_type="loitering", smart_object="dog_cat"),
    DetectionDefinition("forgotten_item", "Vergessener Gegenstand", "Smart-AI-Zonen", smart_type="legacy"),
    DetectionDefinition("taken_item", "Entfernter Gegenstand", "Smart-AI-Zonen", smart_type="loss"),
)

ALL_DETECTIONS: tuple[DetectionDefinition, ...] = BASE_DETECTIONS + SMART_AI_DETECTIONS

_DIRECT_TOKEN_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("non_motor_vehicle", ("nonmotor", "non_motor", "non-motor", "bicycle", "bike", "cyclist")),
    ("crossline_person", ("crossline people", "crossline person", "linecross people", "linecross person")),
    ("crossline_vehicle", ("crossline vehicle", "linecross vehicle")),
    ("crossline_dog_cat", ("crossline dog", "crossline cat", "crossline dog_cat", "linecross dog", "linecross cat")),
    ("intrusion_person", ("intrusion people", "intrusion person")),
    ("intrusion_vehicle", ("intrusion vehicle",)),
    ("intrusion_dog_cat", ("intrusion dog", "intrusion cat", "intrusion dog_cat")),
    ("linger_person", ("loitering people", "loitering person", "linger people", "linger person")),
    ("linger_vehicle", ("loitering vehicle", "linger vehicle")),
    ("linger_dog_cat", ("loitering dog", "loitering cat", "linger dog", "linger cat")),
    ("forgotten_item", ("forgotten", "left item", "legacy")),
    ("taken_item", ("taken", "removed item", "loss")),
    ("package", ("package", "parcel")),
    ("visitor", ("visitor", "doorbell", "dingdong", "ding dong")),
    ("person", ("person", "people", "human")),
    ("vehicle", ("vehicle", "car", "truck")),
    ("animal", ("animal",)),
    ("pet", ("pet", "dog_cat", "dog", "cat")),
    ("face", ("face",)),
    ("cry", ("cry", "babycry", "baby cry")),
    ("io_input", ("ioinput", "io input", "alarm input")),
    ("sleep", ("sleep", "sleeping")),
    ("motion", ("motion", "cellmotion", "motiondetector", "isMotion")),
)


def definitions() -> tuple[DetectionDefinition, ...]:
    return ALL_DETECTIONS


def definition_by_key(key: str) -> DetectionDefinition | None:
    return next((definition for definition in ALL_DETECTIONS if definition.key == key), None)


def catalog_rows(channel: int | None = None, *, prefix_channel: bool = False) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for definition in ALL_DETECTIONS:
        key = definition.key if not prefix_channel or channel is None else f"ch{channel}:{definition.key}"
        label = definition.label if channel is None else f"Kanal {channel + 1}: {definition.label}"
        rows.append(
            {
                "key": key,
                "label": label,
                "category": definition.category,
                "channel": channel,
                "supported": False,
                "active": False,
                "source": "catalog",
                "raw_value": None,
            }
        )
    return rows


def normalize_detection_key(raw_parts: Iterable[object]) -> str | None:
    text = " ".join(str(part) for part in raw_parts if part is not None)
    if not text:
        return None
    normalized = re.sub(r"[^a-z0-9_ -]+", " ", text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    compact = normalized.replace(" ", "").replace("-", "_")

    for key, tokens in _DIRECT_TOKEN_MAP:
        for token in tokens:
            normalized_token = token.lower()
            compact_token = normalized_token.replace(" ", "").replace("-", "_")
            if normalized_token in normalized or compact_token in compact:
                return key
    return None

