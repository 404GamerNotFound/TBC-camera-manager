from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class DetectionDefinition:
    key: str
    label: str
    category: str


DIRECT_TOKEN_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
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
    ("motion", ("motion", "cellmotion", "motiondetector", "ismotion")),
)


def normalize_detection_key(raw_parts: Iterable[object]) -> str | None:
    text = " ".join(str(part) for part in raw_parts if part is not None)
    if not text:
        return None
    normalized = re.sub(r"[^a-z0-9_ -]+", " ", text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    compact = normalized.replace(" ", "").replace("-", "_")

    for key, tokens in DIRECT_TOKEN_MAP:
        for token in tokens:
            normalized_token = token.lower()
            compact_token = normalized_token.replace(" ", "").replace("-", "_")
            if normalized_token in normalized or compact_token in compact:
                return key
    return None
