from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

LOGGER = logging.getLogger(__name__)

PTZ_COMMANDS = frozenset(
    {"Stop", "Left", "Right", "Up", "Down", "LeftUp", "LeftDown", "RightUp", "RightDown", "ZoomInc", "ZoomDec"}
)

PTZ_PAN_TILT: dict[str, tuple[float, float]] = {
    "Up": (0.0, 1.0),
    "Down": (0.0, -1.0),
    "Left": (-1.0, 0.0),
    "Right": (1.0, 0.0),
    "LeftUp": (-1.0, 1.0),
    "LeftDown": (-1.0, -1.0),
    "RightUp": (1.0, 1.0),
    "RightDown": (1.0, -1.0),
}
PTZ_ZOOM: dict[str, float] = {"ZoomInc": 1.0, "ZoomDec": -1.0}


def _camera(host: str, port: int, username: str, password: str) -> Any:
    from onvif import ONVIFCamera

    return ONVIFCamera(host, port, username, password, no_cache=True, encrypt=True, adjust_time=True)


def _profile_token(camera: Any) -> str | None:
    profiles = camera.create_media_service().GetProfiles()
    return profiles[0].token if profiles else None


def ptz_capability(*, host: str, port: int, username: str, password: str) -> dict[str, Any]:
    """Probe whether the camera's ONVIF media profile advertises PTZ support.

    Many consumer cameras (TP-Link/Tapo among them) only expose PTZ on some
    models/firmwares; a plain device probe does not reveal this, so a
    dedicated PTZ-configuration lookup is required.
    """
    try:
        camera = _camera(host, port, username, password)
        token = _profile_token(camera)
        if token is None:
            return {"ptz_supported": False}
        configurations = camera.create_ptz_service().GetConfigurations()
        return {"ptz_supported": bool(configurations)}
    except Exception as exc:
        LOGGER.info("ONVIF PTZ capability probe failed for %s:%s: %s", host, port, exc)
        return {"ptz_supported": False}


def ptz_move(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    command: str,
    speed: int | None = None,
    pulse_seconds: float = 0.5,
) -> None:
    camera = _camera(host, port, username, password)
    token = _profile_token(camera)
    if token is None:
        raise RuntimeError("ONVIF: Kein Medienprofil für PTZ gefunden")
    ptz_service = camera.create_ptz_service()

    if command == "Stop":
        ptz_service.Stop({"ProfileToken": token})
        return

    factor = max(0.1, min(1.0, (speed or 50) / 100))
    velocity: dict[str, Any] = {}
    if command in PTZ_ZOOM:
        velocity["Zoom"] = {"x": PTZ_ZOOM[command] * factor}
    elif command in PTZ_PAN_TILT:
        pan, tilt = PTZ_PAN_TILT[command]
        velocity["PanTilt"] = {"x": pan * factor, "y": tilt * factor}
    else:
        raise ValueError(f"Unbekannter PTZ-Befehl: {command}")

    ptz_service.ContinuousMove({"ProfileToken": token, "Velocity": velocity})
    time.sleep(max(0.1, min(3.0, pulse_seconds)))
    try:
        ptz_service.Stop({"ProfileToken": token})
    except Exception:
        LOGGER.debug("ONVIF PTZ stop pulse failed", exc_info=True)


async def get_ptz_control_state(camera: dict[str, Any], *, default_port: int = 80) -> dict[str, Any]:
    """CameraModule.get_control_state() shape for modules that only offer ONVIF PTZ.

    Shared by every ONVIF-based module (TP-Link/Tapo, Standard ONVIF, Aqara):
    none of them expose floodlight/PIR/siren/reboot/battery over plain ONVIF,
    so those fields are always reported as unsupported.
    """
    result = await asyncio.to_thread(
        ptz_capability,
        host=camera["host"],
        port=int(camera.get("onvif_port") or default_port),
        username=camera["username"],
        password=camera["password"],
    )
    return {
        "ptz_supported": bool(result.get("ptz_supported")),
        "floodlight_supported": False,
        "floodlight_state": None,
        "pir_supported": False,
        "pir_enabled": None,
        "reboot_supported": False,
        "siren_supported": False,
        "is_battery": False,
        "battery_percentage": None,
        "battery_temperature": None,
        "battery_status": None,
    }


async def send_ptz_control(camera: dict[str, Any], *, action: str, default_port: int = 80, **params: Any) -> dict[str, Any]:
    if action != "ptz":
        raise ValueError(f"Dieses Modul unterstützt die Aktion '{action}' nicht über ONVIF")
    command = str(params.get("command") or "").strip()
    if command not in PTZ_COMMANDS:
        raise ValueError(f"Unbekannter PTZ-Befehl: {command}")
    await asyncio.to_thread(
        ptz_move,
        host=camera["host"],
        port=int(camera.get("onvif_port") or default_port),
        username=camera["username"],
        password=camera["password"],
        command=command,
        speed=params.get("speed"),
        pulse_seconds=float(params.get("pulse_seconds") or 0.5),
    )
    return {"status": "ok", "action": action}
