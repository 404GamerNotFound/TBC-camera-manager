from __future__ import annotations

from dataclasses import dataclass, field

from .backend import Detection


@dataclass(frozen=True)
class TrackedDetection:
    label: str
    detection_key: str
    confidence: float
    box: tuple[float, float, float, float]
    track_id: int


@dataclass
class _Track:
    track_id: int
    detection_key: str
    label: str
    confidence: float
    box: tuple[float, float, float, float]
    hits: int
    misses: int


def _iou(box_a: tuple[float, float, float, float], box_b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


@dataclass
class ObjectTracker:
    """Assigns persistent track IDs to detections across frames via greedy IoU matching.

    Matching is scoped per detection_key (class) so a person and a car never merge into
    the same track. A track is only surfaced in update()'s return value once it has been
    matched min_hits times in a row - this is what suppresses a single-frame false-positive
    flicker from ever reaching the active/recording/loitering layers, since a real object
    needs to persist across at least two inference cycles before it counts as "seen". A
    track survives up to max_missed consecutive cycles without a match (e.g. one dropped
    inference frame) before it is dropped, mirroring the hysteresis ActiveObjectTracker
    already applies on the way back down to "inactive".
    """

    iou_threshold: float = 0.3
    min_hits: int = 2
    max_missed: int = 3
    _tracks: dict[int, _Track] = field(default_factory=dict)
    _next_id: int = field(default=1)

    def update(self, detections: list[Detection]) -> list[TrackedDetection]:
        by_class: dict[str, list[Detection]] = {}
        for detection in detections:
            by_class.setdefault(detection.detection_key, []).append(detection)

        classes = set(by_class) | {track.detection_key for track in self._tracks.values()}
        confirmed: list[TrackedDetection] = []

        for detection_key in classes:
            class_tracks = {tid: track for tid, track in self._tracks.items() if track.detection_key == detection_key}
            class_detections = by_class.get(detection_key, [])

            candidates = sorted(
                (
                    (_iou(track.box, detection.box), tid, index)
                    for tid, track in class_tracks.items()
                    for index, detection in enumerate(class_detections)
                ),
                key=lambda candidate: candidate[0],
                reverse=True,
            )

            matched_tids: set[int] = set()
            matched_indices: set[int] = set()
            for iou_score, tid, index in candidates:
                if iou_score < self.iou_threshold or tid in matched_tids or index in matched_indices:
                    continue
                matched_tids.add(tid)
                matched_indices.add(index)
                track = class_tracks[tid]
                detection = class_detections[index]
                track.box = detection.box
                track.confidence = detection.confidence
                track.label = detection.label
                track.hits += 1
                track.misses = 0
                if track.hits >= self.min_hits:
                    confirmed.append(_tracked_detection(track))

            for tid, track in list(class_tracks.items()):
                if tid in matched_tids:
                    continue
                track.misses += 1
                if track.misses > self.max_missed:
                    self._tracks.pop(tid, None)

            for index, detection in enumerate(class_detections):
                if index in matched_indices:
                    continue
                track = _Track(
                    track_id=self._next_id,
                    detection_key=detection_key,
                    label=detection.label,
                    confidence=detection.confidence,
                    box=detection.box,
                    hits=1,
                    misses=0,
                )
                self._tracks[track.track_id] = track
                self._next_id += 1
                if track.hits >= self.min_hits:
                    confirmed.append(_tracked_detection(track))

        return confirmed


def _tracked_detection(track: _Track) -> TrackedDetection:
    return TrackedDetection(
        label=track.label,
        detection_key=track.detection_key,
        confidence=track.confidence,
        box=track.box,
        track_id=track.track_id,
    )
