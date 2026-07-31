from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import IO

import numpy as np

from ..live import redact_rtsp_credentials

LOGGER = logging.getLogger(__name__)

SAMPLE_RATE = 16000
# 0.96s per window - the patch length the reference AudioSet/YAMNet-style classifiers
# are trained against (96 * 10ms mel-spectrogram frames internally).
WINDOW_SAMPLES = 15360


class AudioGrabber:
    """Long-lived ffmpeg process emitting raw mono 16kHz PCM for a single camera stream.

    Mirrors FrameGrabber, but demuxes the audio track instead of the video track
    (-vn instead of -an). Not every camera stream carries audio at all - if ffmpeg
    exits immediately without producing a single full window, is_likely_silent()
    lets the caller stop retrying instead of looping forever on a stream that will
    never have audio.
    """

    def __init__(self, stream_uri: str) -> None:
        self.stream_uri = stream_uri
        self._window_bytes = WINDOW_SAMPLES * 2  # 16-bit samples
        self._process: subprocess.Popen | None = None
        self._stderr_messages: list[str] = []

    def start(self) -> None:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg is not installed")
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
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-f",
            "s16le",
            "pipe:1",
        ]
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=self._window_bytes * 2,
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

    def read_window(self) -> np.ndarray | None:
        """Blocks until one full WINDOW_SAMPLES window is available, as float32 PCM in [-1, 1]."""
        process = self._process
        if process is None or process.stdout is None:
            return None
        raw = _read_exact(process.stdout, self._window_bytes)
        if raw is None:
            return None
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return samples

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
