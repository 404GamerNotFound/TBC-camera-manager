from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .classes import line_crossing_key_for
from .tracking import TrackedDetection
from .zones import box_centroid

# A single missed inference cycle inside a line zone should not lose a track's last known
# position - mirrors loitering.py's LOITER_GRACE_SECONDS hysteresis, applied here to centroid
# history instead of dwell time.
CENTROID_GRACE_SECONDS = 3.0

# Same "stays active for a few seconds after firing" window ActiveObjectTracker already uses
# elsewhere, so a single-frame crossing event reads as a brief pulse in detection_rows() instead
# of vanishing before the next detection_rows() call ever sees it.
TRIGGER_ACTIVE_SECONDS = 3.0


def _orientation(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> int:
    value = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _on_segment(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> bool:
    """True if q lies on the segment p-r, given p/q/r are already known collinear."""
    return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])


def segments_intersect(
    p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float], p4: tuple[float, float]
) -> bool:
    """Standard orientation-based 2D segment intersection test (p1-p2 vs p3-p4).

    Used to test whether a track's motion this frame (its previous centroid to its current one)
    actually crossed a line zone's two-point segment, rather than just comparing which side of
    the line's *infinite extension* the point is on - which would incorrectly count a track that
    never came near the drawn segment at all.
    """
    o1 = _orientation(p1, p2, p3)
    o2 = _orientation(p1, p2, p4)
    o3 = _orientation(p3, p4, p1)
    o4 = _orientation(p3, p4, p2)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_segment(p1, p3, p2):
        return True
    if o2 == 0 and _on_segment(p1, p4, p2):
        return True
    if o3 == 0 and _on_segment(p3, p1, p4):
        return True
    if o4 == 0 and _on_segment(p3, p2, p4):
        return True
    return False


def crossing_side(point: tuple[float, float], line_p1: tuple[float, float], line_p2: tuple[float, float]) -> float:
    """Signed cross product of (line_p2 - line_p1) and (point - line_p1).

    The sign depends only on the line's draw order (line_p1 -> line_p2), not on where exactly a
    track crosses it - the zone editor draws a direction arrow using this same convention so the
    admin always sees, while drawing, which side counts as "in".
    """
    return (line_p2[0] - line_p1[0]) * (point[1] - line_p1[1]) - (line_p2[1] - line_p1[1]) * (point[0] - line_p1[0])


@dataclass
class LineCrossingTracker:
    """Detects a tracked object's centroid crossing a 'line' zone's segment, and which direction.

    Presence is tracked per (zone_id, track_id), using the track IDs ObjectTracker assigns - the
    same keying LoiterTracker uses, and for the same reason: a track's own previous centroid is
    the only history kept anywhere in this pipeline (TrackedDetection itself carries none).
    """

    _last_centroid: dict[tuple[int, int], tuple[float, float]] = field(default_factory=dict)
    _last_seen: dict[tuple[int, int], float] = field(default_factory=dict)
    _active_until: dict[str, float] = field(default_factory=dict)

    def update(
        self, detections: list[TrackedDetection], zones: list[dict[str, Any]], *, now: float | None = None
    ) -> list[tuple[int, str, str]]:
        """Returns (zone_id, detection_key, direction) for every crossing that happened this
        call, for the caller to persist as a count increment - detection_rows() itself only needs
        the momentary trigger keys, via active_trigger_keys() below."""
        now = now if now is not None else time.time()
        crossings: list[tuple[int, str, str]] = []
        for zone in zones:
            if zone.get("mode") != "line":
                continue
            points = zone.get("points") or []
            if len(points) != 2:
                continue
            zone_id = zone["id"]
            line_p1, line_p2 = tuple(points[0]), tuple(points[1])
            allowed_classes = zone.get("classes")
            for detection in detections:
                if allowed_classes and detection.detection_key not in allowed_classes:
                    continue
                centroid = box_centroid(detection.box)
                key = (zone_id, detection.track_id)
                previous = self._last_centroid.get(key)
                self._last_centroid[key] = centroid
                self._last_seen[key] = now
                if previous is None:
                    continue
                if not segments_intersect(previous, centroid, line_p1, line_p2):
                    continue
                direction = "in" if crossing_side(centroid, line_p1, line_p2) > 0 else "out"
                crossings.append((zone_id, detection.detection_key, direction))
                trigger_key = line_crossing_key_for(detection.detection_key, direction)
                if trigger_key:
                    self._active_until[trigger_key] = now + TRIGGER_ACTIVE_SECONDS

        expired = [key for key, last_seen in self._last_seen.items() if now - last_seen > CENTROID_GRACE_SECONDS]
        for key in expired:
            self._last_centroid.pop(key, None)
            self._last_seen.pop(key, None)

        return crossings

    def active_trigger_keys(self, *, now: float | None = None) -> set[str]:
        now = now if now is not None else time.time()
        return {key for key, until in self._active_until.items() if until > now}
