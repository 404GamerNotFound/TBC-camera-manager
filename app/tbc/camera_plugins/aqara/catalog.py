from __future__ import annotations

import json
from pathlib import Path

from ...camera_modules.detections import DetectionDefinition


def _load_definitions() -> tuple[DetectionDefinition, ...]:
    path = Path(__file__).resolve().parent / "detections.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return tuple(DetectionDefinition(**row) for row in rows)


AQARA_DETECTIONS = _load_definitions()


def definitions() -> tuple[DetectionDefinition, ...]:
    return AQARA_DETECTIONS


def catalog_rows(supported_keys: set[str]) -> list[dict[str, object]]:
    return [
        {
            "key": definition.key,
            "label": definition.label,
            "category": definition.category,
            "channel": None,
            "supported": definition.key in supported_keys,
            "active": False,
            "source": "aqara/onvif" if definition.key in supported_keys else "aqara/catalog",
            "raw_value": None,
        }
        for definition in AQARA_DETECTIONS
    ]
