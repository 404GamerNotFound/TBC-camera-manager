from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import database
from .backend import Detection, DetectionBackend
from .classes import DETECTION_KEY_LABELS, LOITERING_KEY_LABELS
from .frame_source import FrameGrabber
from .loitering import LoiterTracker
from .tracking import ObjectTracker, TrackedDetection
from .zones import filter_detections_by_zones

LOGGER = logging.getLogger(__name__)

DetectionCallback = Callable[[int, list[dict[str, Any]]], None]
BackendFactory = Callable[[dict[str, Any], str | None], DetectionBackend]
FrameDetectionCallback = Callable[[int, Any, list[Detection]], None]


@dataclass
class ActiveObjectTracker:
    """Turns per-frame detections into stable active/inactive rows for camera_detections.

    A class stays "active" for active_timeout_seconds after it was last seen, so a
    single missed/failed inference cycle does not flap the state back to inactive.
    """

    active_timeout_seconds: float = 3.0
    _last_seen: dict[str, float] = field(default_factory=dict)
    _last_detection: dict[str, Detection | TrackedDetection] = field(default_factory=dict)

    def update(self, detections: list[Detection] | list[TrackedDetection], *, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        for detection in detections:
            self._last_seen[detection.detection_key] = now
            self._last_detection[detection.detection_key] = detection

    def detection_rows(self, *, now: float | None = None) -> list[dict[str, Any]]:
        now = now if now is not None else time.time()
        rows: list[dict[str, Any]] = []
        for key, label in DETECTION_KEY_LABELS.items():
            seen_at = self._last_seen.get(key)
            active = seen_at is not None and (now - seen_at) <= self.active_timeout_seconds
            detection = self._last_detection.get(key) if active else None
            raw_value = None
            if detection is not None:
                payload: dict[str, Any] = {"confidence": round(detection.confidence, 3), "box": list(detection.box)}
                track_id = getattr(detection, "track_id", None)
                if track_id is not None:
                    payload["track_id"] = track_id
                raw_value = json.dumps(payload)
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "category": "ai",
                    "channel": None,
                    "supported": True,
                    "active": active,
                    "source": "local_ai",
                    "raw_value": raw_value,
                }
            )
        return rows


def _loitering_rows(loiter_tracker: LoiterTracker, zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active_keys = loiter_tracker.active_loitering_keys(zones)
    return [
        {
            "key": key,
            "label": label,
            "category": "ai",
            "channel": None,
            "supported": True,
            "active": key in active_keys,
            "source": "local_ai",
            "raw_value": None,
        }
        for key, label in LOITERING_KEY_LABELS.items()
    ]


async def run_camera_detection_worker(
    database_path: str,
    camera_id: int,
    *,
    backend_factory: BackendFactory,
    on_detections: DetectionCallback,
    on_frame_detections: FrameDetectionCallback | None = None,
) -> None:
    while True:
        camera = database.get_camera(database_path, camera_id)
        settings = database.get_camera_detection_settings(database_path, camera_id)
        if camera is None or int(camera.get("enabled") or 0) != 1:
            return
        if settings is None or not settings.get("enabled") or not camera.get("stream_uri"):
            return
        try:
            await _run_worker_once(
                database_path,
                camera_id,
                camera["stream_uri"],
                camera.get("module_key"),
                settings,
                backend_factory,
                on_detections,
                on_frame_detections,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("Lokale KI-Erkennung für Kamera %s unterbrochen: %s", camera_id, exc)
            await asyncio.sleep(15)


async def _run_worker_once(
    database_path: str,
    camera_id: int,
    stream_uri: str,
    module_key: str | None,
    settings: dict[str, Any],
    backend_factory: BackendFactory,
    on_detections: DetectionCallback,
    on_frame_detections: FrameDetectionCallback | None = None,
) -> None:
    sample_fps = float(settings.get("sample_fps") or 2.0)
    grabber = FrameGrabber(stream_uri, sample_fps=sample_fps)
    tracker = ActiveObjectTracker(active_timeout_seconds=max(3.0, 3.0 / sample_fps))
    object_tracker = ObjectTracker()
    loiter_tracker = LoiterTracker()
    # A plugin-bundled model may need downloading on first use - keep that (and the
    # rest of backend construction) off the event loop so it doesn't stall other
    # cameras' workers.
    backend = await asyncio.to_thread(backend_factory, settings, module_key)
    zones = database.list_camera_detection_zones(database_path, camera_id)
    grabber.start()
    try:
        consecutive_failures = 0
        while True:
            frame = await asyncio.to_thread(grabber.read_frame)
            if frame is None:
                consecutive_failures += 1
                if consecutive_failures >= 5 or not grabber.is_running():
                    raise RuntimeError(grabber.last_message() or "Kein Frame vom Erkennungs-Stream erhalten")
                await asyncio.sleep(1)
                continue
            consecutive_failures = 0
            detections = await asyncio.to_thread(backend.infer, frame)
            # Assign persistent track IDs before anything else touches the detections -
            # a track is only returned here once it has matched min_hits times in a row,
            # which is what filters out single-frame false-positive flicker.
            tracked_detections = object_tracker.update(detections)
            # Loitering uses the raw, pre-zone-filter tracked detections - it is its own
            # zone type independent of include/exclude filtering below.
            loiter_tracker.update(tracked_detections, zones)
            filtered_detections = filter_detections_by_zones(tracked_detections, zones)
            tracker.update(filtered_detections)
            rows = tracker.detection_rows() + _loitering_rows(loiter_tracker, zones)
            on_detections(camera_id, rows)
            if on_frame_detections is not None and filtered_detections:
                on_frame_detections(camera_id, frame, filtered_detections)
    finally:
        grabber.stop()


async def detection_supervisor(
    database_path: str,
    *,
    on_detections: DetectionCallback,
    backend_factory: BackendFactory,
    on_frame_detections: FrameDetectionCallback | None = None,
    reconcile_interval_seconds: float = 10.0,
) -> None:
    """Keeps one detection worker task per enabled camera with local AI detection turned on.

    Mirrors _camera_event_supervisor in main.py: a dict[camera_id, (fingerprint, task)],
    reconciled periodically so config changes restart the affected worker cleanly.
    """
    workers: dict[int, tuple[tuple[Any, ...], asyncio.Task[None]]] = {}
    await asyncio.sleep(3)
    try:
        while True:
            wanted: dict[int, tuple[Any, ...]] = {}
            for camera in database.list_cameras(database_path):
                camera_id = int(camera["id"])
                if int(camera.get("enabled") or 0) != 1 or not camera.get("stream_uri"):
                    continue
                settings = database.get_camera_detection_settings(database_path, camera_id)
                if not settings or not settings.get("enabled"):
                    continue
                zones = database.list_camera_detection_zones(database_path, camera_id)
                zones_fingerprint = tuple(
                    (zone["id"], zone["mode"], zone["classes_json"], zone["points_json"], zone["updated_at"])
                    for zone in zones
                )
                wanted[camera_id] = (
                    camera.get("stream_uri"),
                    settings.get("sample_fps"),
                    settings.get("confidence_threshold"),
                    settings.get("backend"),
                    zones_fingerprint,
                )
            for camera_id, (fingerprint, task) in list(workers.items()):
                if task.done() or wanted.get(camera_id) != fingerprint:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    workers.pop(camera_id, None)
            for camera_id, fingerprint in wanted.items():
                if camera_id not in workers:
                    task = asyncio.create_task(
                        run_camera_detection_worker(
                            database_path,
                            camera_id,
                            backend_factory=backend_factory,
                            on_detections=on_detections,
                            on_frame_detections=on_frame_detections,
                        )
                    )
                    workers[camera_id] = (fingerprint, task)
            await asyncio.sleep(reconcile_interval_seconds)
    finally:
        for _, task in workers.values():
            task.cancel()
        if workers:
            await asyncio.gather(*(task for _, task in workers.values()), return_exceptions=True)
