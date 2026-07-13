from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import database
from .backend import Detection, DetectionBackend
from .classes import DETECTION_KEY_LABELS
from .frame_source import FrameGrabber
from .zones import filter_detections_by_zones

LOGGER = logging.getLogger(__name__)

DetectionCallback = Callable[[int, list[dict[str, Any]]], None]
BackendFactory = Callable[[dict[str, Any]], DetectionBackend]


@dataclass
class ActiveObjectTracker:
    """Turns per-frame detections into stable active/inactive rows for camera_detections.

    A class stays "active" for active_timeout_seconds after it was last seen, so a
    single missed/failed inference cycle does not flap the state back to inactive.
    """

    active_timeout_seconds: float = 3.0
    _last_seen: dict[str, float] = field(default_factory=dict)
    _last_detection: dict[str, Detection] = field(default_factory=dict)

    def update(self, detections: list[Detection], *, now: float | None = None) -> None:
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
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "category": "ai",
                    "channel": None,
                    "supported": True,
                    "active": active,
                    "source": "local_ai",
                    "raw_value": (
                        {"confidence": round(detection.confidence, 3), "box": list(detection.box)}
                        if detection is not None
                        else None
                    ),
                }
            )
        return rows


async def run_camera_detection_worker(
    database_path: str,
    camera_id: int,
    *,
    backend_factory: BackendFactory,
    on_detections: DetectionCallback,
) -> None:
    while True:
        camera = database.get_camera(database_path, camera_id)
        settings = database.get_camera_detection_settings(database_path, camera_id)
        if camera is None or int(camera.get("enabled") or 0) != 1:
            return
        if settings is None or not settings.get("enabled") or not camera.get("stream_uri"):
            return
        try:
            await _run_worker_once(database_path, camera_id, camera["stream_uri"], settings, backend_factory, on_detections)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("Lokale KI-Erkennung für Kamera %s unterbrochen: %s", camera_id, exc)
            await asyncio.sleep(15)


async def _run_worker_once(
    database_path: str,
    camera_id: int,
    stream_uri: str,
    settings: dict[str, Any],
    backend_factory: BackendFactory,
    on_detections: DetectionCallback,
) -> None:
    sample_fps = float(settings.get("sample_fps") or 2.0)
    grabber = FrameGrabber(stream_uri, sample_fps=sample_fps)
    tracker = ActiveObjectTracker(active_timeout_seconds=max(3.0, 3.0 / sample_fps))
    backend = backend_factory(settings)
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
            detections = filter_detections_by_zones(detections, zones)
            tracker.update(detections)
            on_detections(camera_id, tracker.detection_rows())
    finally:
        grabber.stop()


async def detection_supervisor(
    database_path: str,
    *,
    on_detections: DetectionCallback,
    backend_factory: BackendFactory,
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
                        )
                    )
                    workers[camera_id] = (fingerprint, task)
            await asyncio.sleep(reconcile_interval_seconds)
    finally:
        for _, task in workers.values():
            task.cancel()
        if workers:
            await asyncio.gather(*(task for _, task in workers.values()), return_exceptions=True)
