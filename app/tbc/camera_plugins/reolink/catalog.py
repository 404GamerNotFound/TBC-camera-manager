from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DetectionDefinition:
    key: str
    label: str
    category: str
    object_type: str | None = None
    capability_key: str | None = None
    smart_type: str | None = None
    smart_object: str | None = None


def _load_definitions() -> tuple[DetectionDefinition, ...]:
    path = Path(__file__).resolve().parent / "detections.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return tuple(DetectionDefinition(**row) for row in rows)


ALL_DETECTIONS: tuple[DetectionDefinition, ...] = _load_definitions()

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
