from __future__ import annotations

import json
from pathlib import Path

from ..camera_modules.detections import DetectionDefinition


def _load_definitions() -> tuple[DetectionDefinition, ...]:
    path = Path(__file__).resolve().parents[1] / "camera_plugins" / "standard_onvif" / "detections.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return tuple(DetectionDefinition(**row) for row in rows)


ONVIF_DETECTIONS = _load_definitions()


def definitions() -> tuple[DetectionDefinition, ...]:
    return ONVIF_DETECTIONS


def catalog_rows(supported_keys: set[str], *, source: str = "onvif-events") -> list[dict[str, object]]:
    return [
        {
            "key": definition.key,
            "label": definition.label,
            "category": definition.category,
            "channel": None,
            "supported": definition.key in supported_keys,
            "active": False,
            "source": source,
            "raw_value": None,
        }
        for definition in ONVIF_DETECTIONS
    ]
