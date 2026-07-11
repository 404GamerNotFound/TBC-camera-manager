from __future__ import annotations

import asyncio
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)

PTZ_COMMANDS = frozenset(
    {"Stop", "Left", "Right", "Up", "Down", "LeftUp", "LeftDown", "RightUp", "RightDown", "ZoomInc", "ZoomDec", "Auto"}
)


async def get_control_state(camera: dict[str, Any], *, channel: int = 0) -> dict[str, Any]:
    host_api = _host(camera)
    try:
        await _call_if_available(host_api, "get_host_data")
        await _call_if_available(host_api, "get_states")
        channel = _resolve_channel(host_api, channel)
        state: dict[str, Any] = {
            "channel": channel,
            "ptz_supported": any(
                _supported(host_api, channel, cap) for cap in ("ptz", "pan_tilt", "pan", "tilt")
            ),
            "floodlight_supported": _supported(host_api, channel, "floodLight"),
            "floodlight_state": _value(host_api, "whiteled_state", channel),
            "pir_supported": _supported(host_api, channel, "PIR"),
            "pir_enabled": _value(host_api, "pir_enabled", channel),
            "reboot_supported": _supported(host_api, None, "reboot"),
            "siren_supported": _supported(host_api, channel, "siren_play") or _supported(host_api, None, "siren_play"),
            "is_battery": _supported(host_api, channel, "battery"),
            "battery_percentage": _value(host_api, "battery_percentage", channel),
            "battery_temperature": _value(host_api, "battery_temperature", channel),
            "battery_status": _battery_status_label(_value(host_api, "battery_status", channel)),
        }
        return state
    finally:
        await _close_host(host_api)


async def send_control(camera: dict[str, Any], *, action: str, channel: int = 0, **params: Any) -> dict[str, Any]:
    host_api = _host(camera)
    try:
        await _call_if_available(host_api, "get_host_data")
        await _call_if_available(host_api, "get_states")
        channel = _resolve_channel(host_api, channel)
        if action == "ptz":
            await _send_ptz(host_api, channel, params)
        elif action == "floodlight":
            await host_api.set_whiteled(channel, state=bool(params.get("state")))
        elif action == "pir":
            await host_api.set_pir(channel, enable=bool(params.get("enable")))
        elif action == "reboot":
            await host_api.reboot(channel)
        elif action == "siren":
            duration = max(1, min(30, int(params.get("duration") or 5)))
            await host_api.set_siren(channel, enable=True, duration=duration)
        else:
            raise ValueError(f"Unbekannte Steuerungsaktion: {action}")
        return {"status": "ok", "action": action}
    finally:
        await _close_host(host_api)


async def _send_ptz(host_api: Any, channel: int, params: dict[str, Any]) -> None:
    command = str(params.get("command") or "").strip()
    if command not in PTZ_COMMANDS:
        raise ValueError(f"Unbekannter PTZ-Befehl: {command}")
    speed = params.get("speed")
    kwargs: dict[str, Any] = {"command": command}
    if speed is not None:
        kwargs["speed"] = int(speed)
    await host_api.set_ptz_command(channel, **kwargs)
    if command not in ("Stop", "Auto"):
        pulse_seconds = max(0.1, min(3.0, float(params.get("pulse_seconds") or 0.5)))
        await asyncio.sleep(pulse_seconds)
        try:
            await host_api.set_ptz_command(channel, command="Stop")
        except Exception:
            LOGGER.debug("Reolink PTZ stop pulse failed", exc_info=True)


def _host(camera: dict[str, Any]) -> Any:
    try:
        from reolink_aio.api import Host
    except ImportError as exc:
        raise RuntimeError("reolink-aio ist nicht installiert") from exc

    port = int(camera.get("http_port") or 80)
    return Host(
        str(camera["host"]),
        str(camera["username"]),
        str(camera["password"]),
        port=port,
        use_https=port == 443,
        timeout=15,
    )


def _resolve_channel(host_api: Any, channel: int) -> int:
    """Map the requested channel onto a channel the connected device actually reports.

    NVR-connected and dual-lens cameras do not always expose channel 0, so
    blindly using the caller's default would make every per-channel
    capability check (PTZ, floodlight, PIR, ...) silently report unsupported.
    """
    channels = list(getattr(host_api, "channels", None) or [0])
    if channel in channels:
        return channel
    return channels[0] if channels else channel


def _supported(host_api: Any, channel: int | None, capability: str) -> bool:
    try:
        return bool(host_api.supported(channel, capability))
    except Exception:
        LOGGER.debug("Reolink capability check failed: %s", capability, exc_info=True)
        return False


def _value(host_api: Any, method_name: str, channel: int) -> Any:
    method = getattr(host_api, method_name, None)
    if not callable(method):
        return None
    try:
        return method(channel)
    except Exception:
        LOGGER.debug("Reolink control value call failed: %s", method_name, exc_info=True)
        return None


def _battery_status_label(raw: Any) -> str | None:
    if raw is None:
        return None
    labels = {0: "discharging", 1: "charging", 2: "chargecomplete"}
    try:
        return labels.get(int(raw), str(raw))
    except (TypeError, ValueError):
        return str(raw)


async def _call_if_available(target: Any, method_name: str, *args: Any) -> Any:
    import inspect

    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    result = method(*args)
    if inspect.isawaitable(result):
        return await result
    return result


async def _close_host(host_api: Any) -> None:
    for close_method in ("logout", "close", "disconnect"):
        try:
            await _call_if_available(host_api, close_method)
        except Exception:
            LOGGER.debug("Reolink control connection close failed: %s", close_method, exc_info=True)
    try:
        await _call_if_available(host_api, "expire_session", False)
    except Exception:
        LOGGER.debug("Reolink control session close failed", exc_info=True)
