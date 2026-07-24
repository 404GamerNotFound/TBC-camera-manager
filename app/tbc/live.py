from __future__ import annotations

import shutil
import socket
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
    # Floor between automatic restart attempts for a stream that crashed on its
    # own (ffmpeg exited without stop() being called) - long enough that a
    # permanently broken source (bad stream, camera offline) doesn't get its
    # ffmpeg process relaunched every single ~3s status poll, forever.
    RETRY_COOLDOWN_SECONDS = 15.0

    def __init__(self, live_path: str) -> None:
        self.live_path = Path(live_path)
        self._processes: dict[str, subprocess.Popen] = {}
        self._messages: dict[str, list[str]] = {}
        self._stopping: set[str] = set()
        self._last_start_attempt: dict[str, float] = {}
        # Incremented on every start() for a key. _read_stderr's background
        # thread is a slow-running loop (its final step, diagnose_stream_open_
        # failure, blocks for up to a few seconds on a socket connect) - if a
        # newer start() for the same key happens while an older attempt's
        # thread is still finishing up, the old thread must not go on to
        # append its (now-stale, describing a superseded attempt) messages
        # into what has since become a different generation's message list.
        # Each thread captures its own generation once and checks it before
        # every append, rather than racing on shared mutable state.
        self._generation: dict[str, int] = {}

    def start(self, key: str, stream_uri: str) -> Path:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg is not installed")
        playlist = self.playlist_path(key)
        process = self._processes.get(key)
        if process and process.poll() is None and playlist.exists():
            return playlist
        self.stop(key)
        self._stopping.discard(key)
        self._last_start_attempt[key] = time.monotonic()
        generation = self._generation.get(key, 0) + 1
        self._generation[key] = generation
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
        threading.Thread(
            target=self._read_stderr, args=(key, process, stream_uri, playlist, generation), daemon=True
        ).start()
        return playlist

    def should_retry(self, key: str) -> bool:
        """True if this stream crashed on its own (status()=="failed") and the
        retry cooldown has elapsed since the last start attempt - i.e. it is due
        for an automatic restart rather than staying dead until the admin
        manually reopens the live page or clicks refresh."""
        if self.status(key) != "failed":
            return False
        last_attempt = self._last_start_attempt.get(key)
        return last_attempt is None or (time.monotonic() - last_attempt) >= self.RETRY_COOLDOWN_SECONDS

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

    def _append_message(self, key: str, generation: int, message: str) -> bool:
        """Appends to key's message list only if `generation` is still the
        current one for that key - see _generation's docstring. Returns
        whether the append happened, so callers can skip follow-up work (like
        logging or the diagnosis probe) for an already-superseded attempt."""
        if self._generation.get(key) != generation:
            return False
        self._messages.setdefault(key, []).append(message)
        self._messages[key] = self._messages[key][-20:]
        return True

    def _read_stderr(
        self, key: str, process: subprocess.Popen, stream_uri: str, playlist: Path, generation: int
    ) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            message = redact_rtsp_credentials(line.strip())
            if not message:
                continue
            if _is_nonfatal_hls_warning(message):
                LOGGER.debug("ffmpeg %s: %s", key, message)
                continue
            if self._append_message(key, generation, message):
                LOGGER.warning("ffmpeg %s: %s", key, message)
        return_code = process.wait()
        if return_code != 0:
            message = f"ffmpeg exited for {key} with code {return_code}"
            if not self._append_message(key, generation, message):
                return
            if key in self._stopping:
                LOGGER.info(message)
                self._stopping.discard(key)
            else:
                LOGGER.error(message)
                # The stream never produced a single HLS segment - i.e. it failed
                # while opening/negotiating the connection, not mid-stream. A raw
                # TCP probe distinguishes "camera unreachable" (fixable on the
                # network/credentials side) from "reachable, but ffmpeg still
                # can't open it" (points at the runtime/host environment instead -
                # see diagnose_stream_open_failure's docstring). This blocks for
                # up to a few seconds, which is exactly why every append above
                # goes through the generation check: a newer start() can and
                # does happen while this is still running.
                if not playlist.exists():
                    diagnosis = diagnose_stream_open_failure(stream_uri)
                    if diagnosis and self._append_message(key, generation, diagnosis):
                        LOGGER.error("Live diagnosis for %s: %s", key, diagnosis)


def diagnose_stream_open_failure(stream_uri: str, *, timeout: float = 3.0) -> str:
    """Distinguishes "camera unreachable" from "reachable, but ffmpeg still
    can't open the stream" for a live stream that failed before producing a
    single HLS segment - by attempting a bare TCP connect to the same host and
    port, independently of ffmpeg.

    A plain socket connect succeeding while ffmpeg's own RTSP/HTTP open fails
    (most often surfacing as "Operation not permitted") rules out the network
    path, the camera being offline, and firewall/credentials as the cause - it
    points at the runtime environment instead (seen repeatedly with virtualized
    setups, e.g. Proxmox VMs, where low-level network syscalls ffmpeg relies on
    behave differently than a plain connect()). If the bare connect itself
    fails, that confirms a genuine reachability problem instead.
    """
    parsed = urlsplit(stream_uri)
    host = parsed.hostname
    if not host:
        return ""
    port = parsed.port or {"http": 80, "https": 443}.get(parsed.scheme.lower(), 554)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return (
            f"Diagnosis: could not open a plain TCP connection to {host}:{port} either ({exc}). "
            "The camera is likely unreachable on the network, powered off, or the host/port is wrong."
        )
    return (
        f"Diagnosis: a plain TCP connection to {host}:{port} succeeds, but ffmpeg still could not open "
        "the stream. This points to the runtime environment (e.g. a virtualized host's network stack) "
        "rather than the camera, its credentials, or TBC itself."
    )


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
