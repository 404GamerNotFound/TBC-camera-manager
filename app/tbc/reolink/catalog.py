from __future__ import annotations

from dataclasses import dataclass


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
