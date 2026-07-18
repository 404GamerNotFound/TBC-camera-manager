from __future__ import annotations

import shutil
import subprocess
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)
RTSP_URI_PATTERN = re.compile(r"rtsps?://[^\s<>\"']+", re.IGNORECASE)


class LiveManager:
    def __init__(self, live_path: str) -> None:
        self.live_path = Path(live_path)
        self._processes: dict[str, subprocess.Popen] = {}
        self._messages: dict[str, list[str]] = {}
        self._stopping: set[str] = set()

    def start(self, key: str, stream_uri: str) -> Path:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg is not installed")
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
        command = _live_ffmpeg_command(stream_uri, segment_pattern, playlist)
        safe_stream_uri = redact_rtsp_credentials(stream_uri)
        self._messages[key] = [f"Starting live stream {key}: {safe_stream_uri}"]
        LOGGER.info("Starting live stream %s with %s", key, safe_stream_uri)
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
            LOGGER.info("Live stream %s was stopped", key)

    def status(self, key: str) -> str:
        process = self._processes.get(key)
        if process and process.poll() is None:
            return "running" if self.playlist_path(key).exists() else "starting"
        if process is not None:
            return "failed"
        return "stopped"

    def message(self, key: str) -> str:
        messages = self._messages.get(key) or []
        for message in reversed(messages):
            if not _is_nonfatal_hls_warning(message):
                return redact_rtsp_credentials(message)
        return ""

    def note(self, key: str, message: str) -> None:
        self._messages.setdefault(key, []).append(message)
        self._messages[key] = self._messages[key][-20:]

    def wait_until_ready(self, key: str, timeout_seconds: float = 8) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout_seconds
        playlist = self.playlist_path(key)
        while time.monotonic() < deadline:
            process = self._processes.get(key)
            if process is not None and process.poll() is not None:
                message = self.message(key) or f"ffmpeg exited with code {process.returncode}"
                return False, message
            if playlist.exists() and playlist.stat().st_size > 0 and ".ts" in playlist.read_text(encoding="utf-8", errors="ignore"):
                return True, "Live playlist is ready"
            time.sleep(0.2)
        return False, self.message(key) or "Timeout starting the live stream"

    def playlist_path(self, key: str) -> Path:
        return self.live_path / key / "index.m3u8"

    def segment_path(self, key: str, filename: str) -> Path:
        return self.live_path / key / filename

    def _read_stderr(self, key: str, process: subprocess.Popen) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            message = redact_rtsp_credentials(line.strip())
            if not message:
                continue
            if _is_nonfatal_hls_warning(message):
                LOGGER.debug("ffmpeg %s: %s", key, message)
                continue
            self._messages.setdefault(key, []).append(message)
            self._messages[key] = self._messages[key][-20:]
            LOGGER.warning("ffmpeg %s: %s", key, message)
        return_code = process.wait()
        if return_code != 0:
            message = f"ffmpeg exited for {key} with code {return_code}"
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


def redact_rtsp_credentials(value: str) -> str:
    """Mask credentials in RTSP URLs without changing the URL used for streaming."""
    def redact(match: re.Match[str]) -> str:
        uri = match.group(0)
        scheme_end = uri.find("://") + 3
        authority_end = uri.find("/", scheme_end)
        authority_end = len(uri) if authority_end == -1 else authority_end
        authority = uri[scheme_end:authority_end]
        if "@" not in authority:
            return uri
        return f"{uri[:scheme_end]}***:***@{authority.rsplit('@', 1)[1]}{uri[authority_end:]}"

    return RTSP_URI_PATTERN.sub(redact, str(value))


def _is_nonfatal_hls_warning(message: str) -> bool:
    return "Timestamps are unset in a packet" in message and "[hls @" in message


def _live_ffmpeg_command(stream_uri: str, segment_pattern: Path, playlist: Path) -> list[str]:
    # -rtsp_transport is a private option of the RTSP demuxer only; ffmpeg
    # hard-fails ("Option rtsp_transport not found") if it's passed for any
    # other input protocol (e.g. a plain http:// bridge stream), so it must
    # be conditional rather than always-on.
    rtsp_only_options = ["-rtsp_transport", "tcp"] if urlsplit(stream_uri).scheme.lower() in ("rtsp", "rtsps") else []
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "+genpts+discardcorrupt",
        *rtsp_only_options,
        "-use_wallclock_as_timestamps",
        "1",
        "-i",
        stream_uri,
        "-an",
        "-c:v",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-muxdelay",
        "0",
        "-muxpreload",
        "0",
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
