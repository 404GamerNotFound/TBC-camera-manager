from __future__ import annotations

import json
from pathlib import Path

from ..camera_modules.detections import DetectionDefinition


def _load_definitions() -> tuple[DetectionDefinition, ...]:
    path = Path(__file__).resolve().parents[1] / "camera_plugins" / "tplink" / "detections.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return tuple(DetectionDefinition(**row) for row in rows)


TAPO_DETECTIONS: tuple[DetectionDefinition, ...] = _load_definitions()


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
