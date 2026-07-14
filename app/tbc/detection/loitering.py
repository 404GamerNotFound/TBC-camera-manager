from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .backend import Detection
from .classes import loitering_key_for
from .zones import box_centroid, point_in_polygon

# A single missed inference cycle (or a momentary detector miss) inside a loiter
# zone should not reset the dwell timer - mirrors ActiveObjectTracker's hysteresis.
LOITER_GRACE_SECONDS = 3.0


@dataclass
class LoiterTracker:
    """Tracks how long a detection class has been continuously present inside
    'loiter' zones, to support a "present for at least N seconds" trigger.

    Presence is tracked per (zone_id, detection_key) pair, not per individual
    object instance - there is no multi-object tracking in this pipeline, so if
    multiple objects of the same class enter and leave a zone in sequence, dwell
    time accumulates as if it were one continuous presence.
    """

    _start: dict[tuple[int, str], float] = field(default_factory=dict)
    _last_seen: dict[tuple[int, str], float] = field(default_factory=dict)

    def update(self, detections: list[Detection], zones: list[dict[str, Any]], *, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        for zone in zones:
            if zone.get("mode") != "loiter":
                continue
            zone_id = zone["id"]
            allowed_classes = zone.get("classes")
            for detection in detections:
                if allowed_classes and detection.detection_key not in allowed_classes:
                    continue
                if not point_in_polygon(box_centroid(detection.box), zone["points"]):
                    continue
                key = (zone_id, detection.detection_key)
                if key not in self._start:
                    self._start[key] = now
                self._last_seen[key] = now

        expired = [key for key, last_seen in self._last_seen.items() if now - last_seen > LOITER_GRACE_SECONDS]
        for key in expired:
            self._start.pop(key, None)
            self._last_seen.pop(key, None)

    def active_loitering_keys(self, zones: list[dict[str, Any]], *, now: float | None = None) -> set[str]:
        now = now if now is not None else time.time()
        min_dwell_by_zone = {zone["id"]: zone.get("min_dwell_seconds") or 10 for zone in zones if zone.get("mode") == "loiter"}
        active: set[str] = set()
        for (zone_id, detection_key), start in self._start.items():
            min_dwell = min_dwell_by_zone.get(zone_id)
            if min_dwell is None or now - start < min_dwell:
                continue
            loitering_key = loitering_key_for(detection_key)
            if loitering_key:
                active.add(loitering_key)
        return active
