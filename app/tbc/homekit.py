"""Apple HomeKit integration: live view only (no Secure Video), via HAP-python.

The accessory driver runs in its own subprocess (spawned by HomeKitManager,
entry point app/tbc/homekit_worker.py), not a thread inside this process -
pyhap.AccessoryDriver.start() only installs asyncio's child-process watcher
(needed to reap the ffmpeg subprocess each camera stream spawns) when it runs
on the main thread of its own process, so a background thread here would be
unreliable. This mirrors Go2rtcManager's shape (app/tbc/go2rtc.py): spawn a
subprocess, tail its stderr on a daemon thread, expose start/stop/status.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pyhap.camera import (
    VIDEO_CODEC_PARAM_LEVEL_TYPES,
    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES,
    Camera,
)

LOGGER = logging.getLogger(__name__)

# A HomeKit bridge exposing hundreds of accessories is a pathological config
# no real household needs - this bounds it defensively, the same way
# MAX_BIRDSEYE_CAMERAS bounds Birdseye's compositor.
MAX_HOMEKIT_CAMERAS = 32

# HomeKit's minimum mandatory H.264 profile/level - not the client's actually
# negotiated v_profile_id/v_level (see start_stream's stream_config docstring
# in pyhap.camera.Camera). Deliberately not matched exactly for v1: every
# HomeKit-compatible client is required to support at least baseline/3.1, and
# doing so avoids extra per-client profile-selection logic for a feature
# that's already narrowly scoped to live view only.
_RESOLUTIONS = [
    [1920, 1080, 30],
    [1280, 720, 30],
    [640, 480, 30],
    [320, 240, 30],
]


def _homekit_ffmpeg_command(stream_uri: str, stream_config: dict[str, Any]) -> list[str]:
    """Builds the ffmpeg command pyhap.camera.Camera.start_stream would have
    run from its own (macOS-webcam-only) default template - same tail
    (SRTP output, negotiated port/key/ssrc/bitrate), but reading from the
    camera's real RTSP/HTTP stream_uri instead of a local webcam."""
    rtsp_only_options = ["-rtsp_transport", "tcp"] if urlsplit(stream_uri).scheme.lower() in ("rtsp", "rtsps") else []
    width = stream_config["width"]
    height = stream_config["height"]
    fps = stream_config["fps"]
    # Not every client sends MAX_BIT_RATE (see pyhap.camera.Camera._start_stream) -
    # 300kbps matches the smallest resolution class in ffmpeg's own default template.
    max_bitrate = stream_config.get("v_max_bitrate", 300)
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "+genpts+discardcorrupt",
        *rtsp_only_options,
        "-i",
        stream_uri,
        "-an",
        "-vcodec",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "baseline",
        "-level",
        "3.1",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-r",
        str(fps),
        "-vf",
        f"scale={width}:{height}",
        "-b:v",
        f"{max_bitrate}k",
        "-bufsize",
        f"{max_bitrate}k",
        "-payload_type",
        "99",
        "-ssrc",
        str(stream_config["v_ssrc"]),
        "-f",
        "rtp",
        "-srtp_out_suite",
        "AES_CM_128_HMAC_SHA1_80",
        "-srtp_out_params",
        stream_config["v_srtp_key"],
        (
            f"srtp://{stream_config['address']}:{stream_config['v_port']}"
            f"?rtcpport={stream_config['v_port']}&localrtcpport={stream_config['v_port']}&pkt_size=1378"
        ),
    ]


class TBCCameraAccessory(Camera):
    """A HomeKit camera accessory backed by a TBC camera's existing stream_uri.

    Live view only - no audio (matching -an used consistently for TBC's other
    ffmpeg pipelines) and no HomeKit Secure Video (encrypted event recording),
    which is a separate, far less documented HAP extension out of scope here.
    """

    def __init__(
        self,
        driver: Any,
        display_name: str,
        *,
        aid: int,
        stream_uri: str,
        snapshot_path: str | None,
        address: str,
    ) -> None:
        self.stream_uri = stream_uri
        self.snapshot_path = Path(snapshot_path) if snapshot_path else None
        options = {
            "video": {
                "codec": {
                    "profiles": [VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["BASELINE"]],
                    "levels": [VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE3_1"]],
                },
                "resolutions": _RESOLUTIONS,
            },
            "audio": {"codecs": []},
            "srtp": True,
            "address": address,
        }
        super().__init__(options, driver, display_name, aid=aid)

    async def start_stream(self, session_info: dict[str, Any], stream_config: dict[str, Any]) -> bool:
        command = _homekit_ffmpeg_command(self.stream_uri, stream_config)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                limit=1024,
            )
        except OSError as exc:
            LOGGER.error("Failed to start HomeKit stream for %s: %s", self.display_name, exc)
            return False
        session_info["process"] = process
        return True

    def get_snapshot(self, image_size: dict[str, Any]) -> bytes:
        if self.snapshot_path and self.snapshot_path.exists():
            return self.snapshot_path.read_bytes()
        return super().get_snapshot(image_size)


class HomeKitManager:
    """Manages the HomeKit accessory bridge subprocess (app/tbc/homekit_worker.py).

    Off by default - only started when an admin enables HomeKit and selects at
    least one camera. Mirrors Go2rtcManager's shape (app/tbc/go2rtc.py)."""

    def __init__(self, persist_path: str, port: int) -> None:
        self.persist_path = Path(persist_path)
        self.port = port
        self._process: subprocess.Popen | None = None
        self._messages: list[str] = []
        self._lock = threading.Lock()

    def start(self, cameras: list[dict[str, Any]], pincode: str) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            if shutil.which("ffmpeg") is None:
                raise RuntimeError("ffmpeg is not installed")
            self.persist_path.mkdir(parents=True, exist_ok=True)
            status_path = self.persist_path / "status.json"
            status_path.unlink(missing_ok=True)
            config_path = self.persist_path / "worker-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "persist_file": str(self.persist_path / "accessory.state"),
                        "status_file": str(status_path),
                        "port": self.port,
                        "pincode": pincode,
                        "cameras": cameras,
                    }
                ),
                encoding="utf-8",
            )
            try:
                process = subprocess.Popen(
                    [sys.executable, "-m", "app.tbc.homekit_worker", str(config_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                raise RuntimeError(f"HomeKit bridge could not be started: {exc}") from exc
            self._process = process
            self._messages = [f"Starting HomeKit bridge with {len(cameras)} camera(s)"]
            LOGGER.info("Starting HomeKit bridge with %d camera(s)", len(cameras))
            threading.Thread(target=self._read_stderr, args=(process,), daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            LOGGER.info("HomeKit bridge was stopped")

    def status(self) -> str:
        process = self._process
        if process is None:
            return "stopped"
        return "running" if process.poll() is None else "failed"

    def message(self) -> str:
        return self._messages[-1] if self._messages else ""

    def pairing_info(self) -> dict[str, Any]:
        """Reads pairing state directly off disk rather than through the
        worker process (which this parent process has no handle into beyond
        its exit code/stderr) - accessory.state is HAP-python's own persisted
        state (survives restarts and even a stopped bridge, so "already
        paired" still shows correctly while disabled); status.json is written
        once by the worker at startup with the current pincode/QR payload."""
        info: dict[str, Any] = {"paired": False, "pincode": None, "xhm_uri": None}
        state_path = self.persist_path / "accessory.state"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                info["paired"] = bool(state.get("paired_clients"))
            except (OSError, ValueError):
                pass
        status_path = self.persist_path / "status.json"
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
                info["pincode"] = status.get("pincode")
                info["xhm_uri"] = status.get("xhm_uri")
            except (OSError, ValueError):
                pass
        return info

    def reset_pairing(self) -> None:
        """Deletes the persisted pairing state so a broken pairing can be
        redone from scratch. Safe to call while stopped; the next start()
        generates a fresh keypair/MAC and forgets every paired client."""
        (self.persist_path / "accessory.state").unlink(missing_ok=True)
        (self.persist_path / "status.json").unlink(missing_ok=True)

    def _read_stderr(self, process: subprocess.Popen) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            message = line.strip()
            if not message:
                continue
            self._messages.append(message)
            self._messages = self._messages[-20:]
            LOGGER.debug("homekit: %s", message)
        return_code = process.wait()
        if return_code != 0 and self._process is process:
            LOGGER.error("HomeKit bridge exited with code %s", return_code)
