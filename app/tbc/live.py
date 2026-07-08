from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


class LiveManager:
    def __init__(self, live_path: str) -> None:
        self.live_path = Path(live_path)
        self._processes: dict[str, subprocess.Popen] = {}

    def start(self, key: str, stream_uri: str) -> Path:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg ist nicht installiert")
        playlist = self.playlist_path(key)
        process = self._processes.get(key)
        if process and process.poll() is None and playlist.exists():
            return playlist
        self.stop(key)
        out_dir = self.live_path / key
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
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
            "delete_segments+append_list",
            str(playlist),
        ]
        self._processes[key] = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return playlist

    def stop(self, key: str) -> None:
        process = self._processes.pop(key, None)
        if process and process.poll() is None:
            process.terminate()

    def status(self, key: str) -> str:
        process = self._processes.get(key)
        if process and process.poll() is None:
            return "running"
        return "stopped"

    def playlist_path(self, key: str) -> Path:
        return self.live_path / key / "index.m3u8"

    def segment_path(self, key: str, filename: str) -> Path:
        return self.live_path / key / filename


def stream_uri_for(camera: dict[str, Any], channel: dict[str, Any] | None = None) -> str | None:
    if channel and channel.get("stream_uri"):
        return str(channel["stream_uri"])
    return str(camera["stream_uri"]) if camera.get("stream_uri") else None

