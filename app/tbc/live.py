from __future__ import annotations

import shutil
import subprocess
import logging
import threading
import time
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class LiveManager:
    def __init__(self, live_path: str) -> None:
        self.live_path = Path(live_path)
        self._processes: dict[str, subprocess.Popen] = {}
        self._messages: dict[str, list[str]] = {}
        self._stopping: set[str] = set()

    def start(self, key: str, stream_uri: str) -> Path:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg ist nicht installiert")
        playlist = self.playlist_path(key)
        process = self._processes.get(key)
        if process and process.poll() is None and playlist.exists():
            return playlist
        self.stop(key)
        self._stopping.discard(key)
        out_dir = self.live_path / key
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        segment_pattern = out_dir / "segment%03d.ts"
        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-rtsp_transport",
            "tcp",
            "-i",
            stream_uri,
            "-an",
            "-c:v",
            "copy",
            "-f",
            "hls",
            "-hls_time",
            "2",
            "-hls_list_size",
            "5",
            "-hls_flags",
            "delete_segments+omit_endlist",
            "-hls_segment_filename",
            str(segment_pattern),
            str(playlist),
        ]
        self._messages[key] = [f"Starte Live-Stream {key}: {stream_uri}"]
        LOGGER.info("Starte Live-Stream %s mit %s", key, stream_uri)
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._processes[key] = process
        threading.Thread(target=self._read_stderr, args=(key, process), daemon=True).start()
        return playlist

    def stop(self, key: str) -> None:
        process = self._processes.pop(key, None)
        if process and process.poll() is None:
            self._stopping.add(key)
            process.terminate()
            LOGGER.info("Live-Stream %s wurde gestoppt", key)

    def status(self, key: str) -> str:
        process = self._processes.get(key)
        if process and process.poll() is None:
            return "running" if self.playlist_path(key).exists() else "starting"
        if process is not None:
            return "failed"
        return "stopped"

    def message(self, key: str) -> str:
        messages = self._messages.get(key) or []
        if not messages:
            return ""
        return messages[-1]

    def wait_until_ready(self, key: str, timeout_seconds: float = 8) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout_seconds
        playlist = self.playlist_path(key)
        while time.monotonic() < deadline:
            process = self._processes.get(key)
            if process is not None and process.poll() is not None:
                message = self.message(key) or f"ffmpeg beendet mit Code {process.returncode}"
                return False, message
            if playlist.exists() and playlist.stat().st_size > 0 and ".ts" in playlist.read_text(encoding="utf-8", errors="ignore"):
                return True, "Live-Playlist ist bereit"
            time.sleep(0.2)
        return False, self.message(key) or "Timeout beim Starten des Live-Streams"

    def playlist_path(self, key: str) -> Path:
        return self.live_path / key / "index.m3u8"

    def segment_path(self, key: str, filename: str) -> Path:
        return self.live_path / key / filename

    def _read_stderr(self, key: str, process: subprocess.Popen) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            message = line.strip()
            if not message:
                continue
            self._messages.setdefault(key, []).append(message)
            self._messages[key] = self._messages[key][-20:]
            LOGGER.warning("ffmpeg %s: %s", key, message)
        return_code = process.wait()
        if return_code != 0:
            message = f"ffmpeg beendet fuer {key} mit Code {return_code}"
            self._messages.setdefault(key, []).append(message)
            if key in self._stopping:
                LOGGER.info(message)
                self._stopping.discard(key)
            else:
                LOGGER.error(message)


def stream_uri_for(camera: dict[str, Any], channel: dict[str, Any] | None = None) -> str | None:
    if channel and channel.get("stream_uri"):
        return str(channel["stream_uri"])
    return str(camera["stream_uri"]) if camera.get("stream_uri") else None
