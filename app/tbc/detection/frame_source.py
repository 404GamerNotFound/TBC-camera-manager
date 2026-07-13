from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import IO

import numpy as np

from ..live import redact_rtsp_credentials

LOGGER = logging.getLogger(__name__)

DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 360


class FrameGrabber:
    """Long-lived ffmpeg process emitting raw BGR frames for a single camera stream.

    Separate from LiveManager, whose HLS output is a stream-copy (-c:v copy) and
    therefore has no decoded frames to read.
    """

    def __init__(self, stream_uri: str, *, sample_fps: float, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> None:
        self.stream_uri = stream_uri
        self.sample_fps = max(0.1, float(sample_fps))
        self.width = width
        self.height = height
        self._frame_size = width * height * 3
        self._process: subprocess.Popen | None = None
        self._stderr_messages: list[str] = []

    def start(self) -> None:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg ist nicht installiert")
        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-rtsp_transport",
            "tcp",
            "-i",
            self.stream_uri,
            "-an",
            "-vf",
            f"fps={self.sample_fps},scale={self.width}:{self.height}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "pipe:1",
        ]
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=self._frame_size * 2,
        )
        threading.Thread(target=self._drain_stderr, args=(self._process,), daemon=True).start()

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def read_frame(self) -> np.ndarray | None:
        process = self._process
        if process is None or process.stdout is None:
            return None
        raw = _read_exact(process.stdout, self._frame_size)
        if raw is None:
            return None
        return np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3))

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def last_message(self) -> str:
        return self._stderr_messages[-1] if self._stderr_messages else ""

    def _drain_stderr(self, process: subprocess.Popen) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            message = redact_rtsp_credentials(line.decode("utf-8", errors="ignore").strip())
            if message:
                self._stderr_messages.append(message)
                self._stderr_messages = self._stderr_messages[-20:]


def _read_exact(stream: IO[bytes], size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
