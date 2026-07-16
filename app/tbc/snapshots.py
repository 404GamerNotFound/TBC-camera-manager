from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .live import redact_rtsp_credentials

LOGGER = logging.getLogger(__name__)


class DashboardSnapshotManager:
    """Creates small, private dashboard images with an atomic file cache."""

    def __init__(self, root: str, *, interval_seconds: int = 600, timeout_seconds: int = 20) -> None:
        self.root = Path(root)
        self.interval_seconds = max(60, int(interval_seconds))
        self.timeout_seconds = max(5, int(timeout_seconds))
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def path_for(self, camera_id: int) -> Path:
        return self.root / f"camera-{int(camera_id)}.jpg"

    def version(self, camera_id: int) -> int | None:
        path = self.path_for(camera_id)
        try:
            return int(path.stat().st_mtime)
        except FileNotFoundError:
            return None

    def is_due(self, camera_id: int, *, now: float | None = None) -> bool:
        version = self.version(camera_id)
        return version is None or (now or time.time()) - version >= self.interval_seconds

    def refresh_if_due(self, camera_id: int, stream_uri: str) -> Path | None:
        destination = self.path_for(camera_id)
        lock = self._lock_for(camera_id)
        with lock:
            if not self.is_due(camera_id):
                return destination
            return self._capture(camera_id, stream_uri, destination)

    def delete(self, camera_id: int) -> None:
        self.path_for(camera_id).unlink(missing_ok=True)

    def _capture(self, camera_id: int, stream_uri: str, destination: Path) -> Path | None:
        if shutil.which("ffmpeg") is None:
            LOGGER.warning("Dashboard-Snapshot für Kamera %s nicht erstellt: ffmpeg fehlt", camera_id)
            return destination if destination.exists() else None
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".camera-{int(camera_id)}-",
            suffix=".jpg",
            dir=self.root,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            str(stream_uri),
            "-an",
            "-frames:v",
            "1",
            "-vf",
            "scale='min(720,iw)':-2",
            "-q:v",
            "4",
            "-y",
            str(temporary),
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            if result.returncode == 0 and temporary.exists() and temporary.stat().st_size > 0:
                temporary.replace(destination)
                return destination
            message = (result.stderr or result.stdout or "ffmpeg lieferte kein Bild").strip().splitlines()
            LOGGER.warning(
                "Dashboard-Snapshot für Kamera %s fehlgeschlagen: %s",
                camera_id,
                redact_rtsp_credentials(message[-1] if message else "unknown error"),
            )
        except subprocess.TimeoutExpired:
            LOGGER.warning("Dashboard-Snapshot für Kamera %s hat das Zeitlimit überschritten", camera_id)
        finally:
            temporary.unlink(missing_ok=True)
        return destination if destination.exists() else None

    def _lock_for(self, camera_id: int) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(int(camera_id), threading.Lock())
