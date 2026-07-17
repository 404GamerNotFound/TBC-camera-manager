from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# go2rtc's own docs state that requests from localhost bypass its HTTP auth
# entirely, even if configured - binding the API to loopback-only and never
# exposing it via Docker/Home Assistant ports is go2rtc's own recommended way
# to embed it behind a trusted app server, not a TBC-specific workaround.
API_BASE_URL = "http://127.0.0.1:1984"

_CONFIG_TEMPLATE = """\
api:
  listen: "127.0.0.1:1984"
log:
  level: warn
webrtc:
  listen: ":8555"
streams: {}
"""


class Go2rtcManager:
    """Manages an optional go2rtc subprocess providing WebRTC (WHEP) live
    view alongside the existing HLS pipeline in live.py. Mirrors LiveManager's
    shape (sync subprocess.Popen, a daemon thread tailing stderr) rather than
    asyncio, for consistency with that class. Off by default - only started
    when an admin enables WebRTC in Live settings (see database.py's
    live_webrtc_enabled column)."""

    def __init__(self, config_dir: str, binary_path: str = "go2rtc") -> None:
        self.config_dir = Path(config_dir)
        self.binary_path = binary_path
        self._process: subprocess.Popen | None = None
        self._messages: list[str] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            if shutil.which(self.binary_path) is None:
                raise RuntimeError("go2rtc is not installed")
            try:
                self.config_dir.mkdir(parents=True, exist_ok=True)
                config_path = self.config_dir / "go2rtc.yaml"
                config_path.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
                LOGGER.info("Starting go2rtc")
                process = subprocess.Popen(
                    [self.binary_path, "-config", str(config_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                # Covers exec failures (e.g. a go2rtc binary built for the
                # wrong CPU architecture) as well as filesystem errors writing
                # the config - callers only need to handle RuntimeError.
                raise RuntimeError(f"go2rtc could not be started: {exc}") from exc
            self._process = process
            threading.Thread(target=self._read_stderr, args=(process,), daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            LOGGER.info("go2rtc was stopped")

    def status(self) -> str:
        process = self._process
        if process is None:
            return "stopped"
        return "running" if process.poll() is None else "failed"

    def message(self) -> str:
        return self._messages[-1] if self._messages else ""

    def register_stream(self, key: str, stream_uri: str) -> None:
        """Idempotent: go2rtc's PUT /api/streams replaces the source for an
        existing name rather than erroring, so this is safe to call on every
        WebRTC view request (mirrors LiveManager.start()'s lazy-start
        pattern - no separate "is it already registered" check needed)."""
        query = urllib.parse.urlencode({"name": key, "src": stream_uri})
        self._api_call("PUT", f"/api/streams?{query}")

    def unregister_stream(self, key: str) -> None:
        query = urllib.parse.urlencode({"src": key})
        self._api_call("DELETE", f"/api/streams?{query}")

    def exchange_sdp(self, key: str, offer_sdp: str) -> str:
        """Forwards a browser's WHEP SDP offer to go2rtc and returns the SDP
        answer. Blocking (real network I/O, real WebRTC/ICE negotiation on
        go2rtc's side) - callers from async routes must wrap this in
        asyncio.to_thread(), the same way app startup already wraps the
        blocking face/plate model downloads."""
        query = urllib.parse.urlencode({"src": key})
        request = urllib.request.Request(
            f"{API_BASE_URL}/api/webrtc?{query}",
            data=offer_sdp.encode("utf-8"),
            headers={"Content-Type": "application/sdp"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"go2rtc did not respond: {exc}") from exc

    def _api_call(self, method: str, path: str) -> None:
        request = urllib.request.Request(f"{API_BASE_URL}{path}", method=method)
        try:
            with urllib.request.urlopen(request, timeout=5):
                pass
        except urllib.error.URLError as exc:
            raise RuntimeError(f"go2rtc did not respond: {exc}") from exc

    def _read_stderr(self, process: subprocess.Popen) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            message = line.strip()
            if not message:
                continue
            self._messages.append(message)
            self._messages = self._messages[-20:]
            LOGGER.debug("go2rtc: %s", message)
        return_code = process.wait()
        if return_code != 0 and self._process is process:
            LOGGER.error("go2rtc exited with code %s", return_code)
