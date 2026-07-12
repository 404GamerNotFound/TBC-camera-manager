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
            "ptz_presets": _ptz_presets(host_api, channel),
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
            "firmware_supported": _supported(host_api, channel, "firmware"),
            "firmware_current": _value(host_api, "camera_sw_version", channel),
            "zoom_supported": _supported(host_api, channel, "zoom"),
            "zoom_position": _value(host_api, "get_zoom", channel),
            "zoom_range": _zoom_focus_range(host_api, channel, "zoom"),
            "focus_supported": _supported(host_api, channel, "focus"),
            "focus_position": _value(host_api, "get_focus", channel),
            "focus_range": _zoom_focus_range(host_api, channel, "focus"),
            "is_doorbell": bool(_value(host_api, "is_doorbell", channel)),
            "quick_reply_supported": _supported(host_api, channel, "play_quick_reply"),
            "quick_reply_options": _quick_reply_options(host_api, channel),
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
        elif action == "zoom":
            await host_api.set_zoom(channel, _required_int(params, "position", label="Zoom-Position"))
        elif action == "focus":
            await host_api.set_focus(channel, _required_int(params, "position", label="Fokus-Position"))
        elif action == "quick_reply":
            await host_api.play_quick_reply(channel, _required_int(params, "file_id", label="Audiodatei"))
        else:
            raise ValueError(f"Unbekannte Steuerungsaktion: {action}")
        return {"status": "ok", "action": action}
    finally:
        await _close_host(host_api)


async def check_firmware(camera: dict[str, Any], *, channel: int = 0) -> dict[str, Any]:
    """Read-only: ask the device and reolink.com whether a newer firmware exists.

    Does not write anything to the camera.
    """
    host_api = _host(camera)
    try:
        await _call_if_available(host_api, "get_host_data")
        channel = _resolve_channel(host_api, channel)
        if not _supported(host_api, channel, "firmware"):
            raise RuntimeError("Firmware-Prüfung wird von diesem Gerät nicht unterstützt")
        current = _value(host_api, "camera_sw_version", channel)
        try:
            await host_api.check_new_firmware(ch_list=[channel])
        except Exception as exc:
            raise RuntimeError(f"Firmware-Prüfung fehlgeschlagen: {exc}") from exc
        available = host_api.firmware_update_available(channel)
        if available is False:
            return {"current": current, "latest": current, "update_available": False, "release_notes": ""}
        if isinstance(available, str):
            return {"current": current, "latest": available, "update_available": True, "release_notes": ""}
        return {
            "current": current,
            "latest": getattr(available, "version_string", None) or str(available),
            "update_available": True,
            "release_notes": getattr(available, "release_notes", "") or "",
        }
    finally:
        await _close_host(host_api)


async def run_firmware_update(camera: dict[str, Any], *, channel: int = 0, progress_callback: Any = None) -> None:
    """Download and flash the firmware reolink.com reports as newer than the device's.

    This writes to the camera and typically reboots it; callers must have
    already confirmed with the user that an update is available (via
    check_firmware) before calling this.
    """
    host_api = _host(camera)
    poll_task: Any = None
    try:
        await _call_if_available(host_api, "get_host_data")
        channel = _resolve_channel(host_api, channel)
        if not _supported(host_api, channel, "firmware"):
            raise RuntimeError("Firmware-Update wird von diesem Gerät nicht unterstützt")
        try:
            await host_api.check_new_firmware(ch_list=[channel])
        except Exception as exc:
            raise RuntimeError(f"Firmware-Prüfung fehlgeschlagen: {exc}") from exc
        if host_api.firmware_update_available(channel) is False:
            raise RuntimeError("Keine neue Firmware verfügbar; bitte zuerst prüfen")

        if progress_callback is not None:

            async def _poll_progress() -> None:
                while True:
                    # reolink-aio does not (yet) expose upload progress through a
                    # public method, only this internal dict the library itself
                    # writes to during update_firmware().
                    progress = getattr(host_api, "_sw_upload_progress", {}).get(channel, 0)
                    progress_callback(progress)
                    if progress >= 100:
                        return
                    await asyncio.sleep(1)

            poll_task = asyncio.create_task(_poll_progress())
        await host_api.update_firmware(channel)
    finally:
        if poll_task is not None:
            poll_task.cancel()
        if progress_callback is not None:
            progress_callback(100)
        await _close_host(host_api)


async def _send_ptz(host_api: Any, channel: int, params: dict[str, Any]) -> None:
    preset = params.get("preset")
    if preset is not None and str(preset).strip():
        try:
            preset_id = int(preset)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Ungültige Preset-ID: {preset}") from exc
        await host_api.set_ptz_command(channel, preset=preset_id)
        return
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


def _required_int(params: dict[str, Any], key: str, *, label: str) -> int:
    value = params.get(key)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Ungültiger Wert für {label}: {value}") from exc


def _zoom_focus_range(host_api: Any, channel: int, key: str) -> dict[str, int]:
    getter = getattr(host_api, "zoom_range", None)
    if not callable(getter):
        return {}
    try:
        sub = dict((getter(channel) or {}).get(key) or {})
        return {"min": int(sub["min"]), "max": int(sub["max"])}
    except Exception:
        return {}


def _quick_reply_options(host_api: Any, channel: int) -> dict[str, str]:
    getter = getattr(host_api, "quick_reply_dict", None)
    if not callable(getter):
        return {}
    try:
        options = dict(getter(channel) or {})
    except Exception:
        LOGGER.debug("Reolink quick-reply lookup failed", exc_info=True)
        return {}
    # -1 is the "off" sentinel reolink-aio uses for the auto-reply *setting*,
    # not a playable clip - exclude it here since this list is only used to
    # offer real audio files to play back on demand.
    return {str(file_id): str(name) for file_id, name in options.items() if isinstance(file_id, int) and file_id >= 0}


def _ptz_presets(host_api: Any, channel: int) -> dict[str, int]:
    getter = getattr(host_api, "ptz_presets", None)
    if not callable(getter):
        return {}
    try:
        presets = getter(channel)
    except Exception:
        LOGGER.debug("Reolink PTZ preset lookup failed", exc_info=True)
        return {}
    try:
        return {str(name): int(preset_id) for name, preset_id in dict(presets).items()}
    except (TypeError, ValueError):
        return {}


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
