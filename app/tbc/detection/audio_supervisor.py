from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import database
from .audio_backend import AudioDetection, AudioDetectionBackend
from .audio_source import AudioGrabber
from .classes import AUDIO_KEY_LABELS

LOGGER = logging.getLogger(__name__)

AudioDetectionCallback = Callable[[int, list[dict[str, Any]]], None]
AudioBackendFactory = Callable[[dict[str, Any]], AudioDetectionBackend]


@dataclass
class ActiveAudioTracker:
    """Same active/inactive hysteresis as ActiveObjectTracker (supervisor.py), for
    audio detection keys instead of vision ones - a class stays "active" for
    active_timeout_seconds after it was last heard, so one missed inference window
    doesn't flap the state back to inactive.
    """

    active_timeout_seconds: float = 3.0
    _last_seen: dict[str, float] = field(default_factory=dict)
    _last_detection: dict[str, AudioDetection] = field(default_factory=dict)

    def update(self, detections: list[AudioDetection], *, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        for detection in detections:
            self._last_seen[detection.detection_key] = now
            self._last_detection[detection.detection_key] = detection

    def detection_rows(self, *, now: float | None = None) -> list[dict[str, Any]]:
        now = now if now is not None else time.time()
        rows: list[dict[str, Any]] = []
        for key, label in AUDIO_KEY_LABELS.items():
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
                    "source": "local_ai_audio",
                    "raw_value": (
                        json.dumps({"confidence": round(detection.confidence, 3)}) if detection is not None else None
                    ),
                }
            )
        return rows


async def run_camera_audio_detection_worker(
    database_path: str,
    camera_id: int,
    *,
    backend_factory: AudioBackendFactory,
    on_detections: AudioDetectionCallback,
) -> None:
    while True:
        camera = database.get_camera(database_path, camera_id)
        settings = database.get_camera_audio_detection_settings(database_path, camera_id)
        if camera is None or int(camera.get("enabled") or 0) != 1:
            return
        if settings is None or not settings.get("enabled") or not camera.get("stream_uri"):
            return
        try:
            await _run_audio_worker_once(
                database_path,
                camera_id,
                camera["stream_uri"],
                settings,
                backend_factory,
                on_detections,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("Lokale Audio-KI-Erkennung für Kamera %s unterbrochen: %s", camera_id, exc)
            await asyncio.sleep(15)


async def _run_audio_worker_once(
    database_path: str,
    camera_id: int,
    stream_uri: str,
    settings: dict[str, Any],
    backend_factory: AudioBackendFactory,
    on_detections: AudioDetectionCallback,
) -> None:
    grabber = AudioGrabber(stream_uri)
    tracker = ActiveAudioTracker()
    # A configured model may need downloading on first use - keep that (and the rest of
    # backend construction) off the event loop, mirroring the video worker.
    backend = await asyncio.to_thread(backend_factory, settings)
    grabber.start()
    try:
        consecutive_failures = 0
        while True:
            window = await asyncio.to_thread(grabber.read_window)
            if window is None:
                consecutive_failures += 1
                if consecutive_failures >= 5 or not grabber.is_running():
                    raise RuntimeError(
                        grabber.last_message() or "No audio received from the detection stream (it may have no audio track)"
                    )
                await asyncio.sleep(1)
                continue
            consecutive_failures = 0
            detections = await asyncio.to_thread(backend.infer, window)
            tracker.update(detections)
            on_detections(camera_id, tracker.detection_rows())
    finally:
        grabber.stop()


async def audio_detection_supervisor(
    database_path: str,
    *,
    on_detections: AudioDetectionCallback,
    backend_factory: AudioBackendFactory,
    reconcile_interval_seconds: float = 10.0,
) -> None:
    """Keeps one audio detection worker task per enabled camera with local audio AI
    turned on. Mirrors detection.supervisor.detection_supervisor for the video pipeline.
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
                settings = database.get_camera_audio_detection_settings(database_path, camera_id)
                if not settings or not settings.get("enabled"):
                    continue
                wanted[camera_id] = (camera.get("stream_uri"), settings.get("confidence_threshold"))
            for camera_id, (fingerprint, task) in list(workers.items()):
                if task.done() or wanted.get(camera_id) != fingerprint:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    workers.pop(camera_id, None)
            for camera_id, fingerprint in wanted.items():
                if camera_id not in workers:
                    task = asyncio.create_task(
                        run_camera_audio_detection_worker(
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
