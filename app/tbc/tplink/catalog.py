from __future__ import annotations

from ..camera_modules.detections import DetectionDefinition


TAPO_DETECTIONS: tuple[DetectionDefinition, ...] = (
    DetectionDefinition("motion", "Bewegung", "Basis"),
    DetectionDefinition("person", "Person", "KI-Objekte"),
    DetectionDefinition("vehicle", "Fahrzeug", "KI-Objekte"),
    DetectionDefinition("pet", "Haustier", "KI-Objekte"),
    DetectionDefinition("cry", "Weinen", "Audio"),
    DetectionDefinition("visitor", "Besucher / Klingel", "Türklingel"),
)


def definitions() -> tuple[DetectionDefinition, ...]:
    return TAPO_DETECTIONS


def catalog_rows(supported_keys: set[str]) -> list[dict[str, object]]:
    return [
        {
            "key": definition.key,
            "label": definition.label,
            "category": definition.category,
            "channel": None,
            "supported": definition.key in supported_keys,
            "active": False,
            "source": "tp-link/onvif",
            "raw_value": None,
        }
        for definition in TAPO_DETECTIONS
    ]
