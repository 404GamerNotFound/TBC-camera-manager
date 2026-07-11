from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ...camera_modules.base import CameraSnapshot
from ...camera_modules.onvif import OnvifProbe, probe_onvif
from .catalog import DetectionDefinition, catalog_rows, definitions

LOGGER = logging.getLogger(__name__)

DetectionCallback = Callable[[list[dict[str, Any]]], Awaitable[None] | None]


async def probe_camera(camera: dict[str, Any]) -> CameraSnapshot:
    onvif_probe_task = asyncio.to_thread(
        probe_onvif,
        host=camera["host"],
        port=int(camera["onvif_port"]),
        username=camera["username"],
        password=camera["password"],
    )
    reolink_task = _probe_reolink(camera)
    onvif_probe, reolink_snapshot = await asyncio.gather(onvif_probe_task, reolink_task)
    return _merge_snapshots(camera, onvif_probe, reolink_snapshot)


def _merge_snapshots(camera: dict[str, Any], onvif_probe: OnvifProbe, reolink_snapshot: CameraSnapshot | None) -> CameraSnapshot:
    base_rows = catalog_rows()
    for row in base_rows:
        if row["key"] in onvif_probe.event_detection_keys:
            row["supported"] = True
            row["source"] = "onvif-events"

    if reolink_snapshot and reolink_snapshot.detections:
        rows_by_key = {row["key"]: row for row in base_rows}
        for row in reolink_snapshot.detections:
            rows_by_key[row["key"]] = row
        detections = list(rows_by_key.values())
    else:
        detections = base_rows

    status = "ok" if onvif_probe.success or (reolink_snapshot and reolink_snapshot.status == "ok") else "error"
    messages = []
    if onvif_probe.message:
        messages.append(onvif_probe.message)
    if reolink_snapshot and reolink_snapshot.message:
        messages.append(reolink_snapshot.message)
    host_hint = _host_hint(str(camera.get("host") or ""))
    if host_hint:
        messages.append(host_hint)

    return CameraSnapshot(
        status=status,
        message=" | ".join(messages),
        manufacturer=(reolink_snapshot.manufacturer if reolink_snapshot else None) or onvif_probe.manufacturer,
        model=(reolink_snapshot.model if reolink_snapshot else None) or onvif_probe.model,
        firmware=(reolink_snapshot.firmware if reolink_snapshot else None) or onvif_probe.firmware,
        serial=(reolink_snapshot.serial if reolink_snapshot else None) or onvif_probe.serial,
        stream_uri=(reolink_snapshot.stream_uri if reolink_snapshot else None)
        or (onvif_probe.stream_uris[0] if onvif_probe.stream_uris else None),
        detections=detections,
        channels=reolink_snapshot.channels if reolink_snapshot else [],
        metrics=reolink_snapshot.metrics if reolink_snapshot else {},
    )


def _host_hint(host: str) -> str | None:
    if host.startswith("192.169."):
        return "Hinweis: Host beginnt mit 192.169; im Heimnetz ist oft 192.168 gemeint."
    return None


async def _probe_reolink(camera: dict[str, Any]) -> CameraSnapshot | None:
    try:
        from reolink_aio.api import Host
    except ImportError:
        return CameraSnapshot("warn", "Reolink-AIO ist nicht installiert; nur ONVIF wurde geprüft")

    http_port = int(camera.get("http_port") or 80)
    host_api = Host(
        camera["host"],
        camera["username"],
        camera["password"],
        port=http_port,
        use_https=http_port == 443,
        timeout=8,
    )
    try:
        await _call_if_available(host_api, "get_host_data")
        await _call_if_available(host_api, "get_states")
        metrics = await _performance_metrics(host_api)

        channels = list(getattr(host_api, "channels", None) or [0])
        detections: list[dict[str, Any]] = []
        multiple_channels = len(channels) > 1
        for channel in channels:
            detections.extend(_channel_rows(host_api, channel, multiple_channels=multiple_channels))

        channel_rows = []
        for channel in channels:
            channel_stream_uri = await _rtsp_stream_uri(host_api, channel)
            channel_rows.append(
                {
                    "channel_index": channel,
                    "name": _safe_camera_value(host_api, "camera_name", channel) or f"Kanal {channel + 1}",
                    "stream_uri": str(channel_stream_uri) if channel_stream_uri else None,
                }
            )

        stream_uri = await _rtsp_stream_uri(host_api, channels[0])
        if stream_uri is not None:
            stream_uri = str(stream_uri)

        return CameraSnapshot(
            status="ok",
            message="Reolink-Status erfolgreich abgefragt",
            manufacturer=str(getattr(host_api, "manufacturer", "Reolink") or "Reolink"),
            model=_safe_camera_value(host_api, "camera_model", None) or str(getattr(host_api, "model", "") or ""),
            firmware=_safe_camera_value(host_api, "camera_sw_version", None) or str(getattr(host_api, "sw_version", "") or ""),
            serial=_safe_camera_value(host_api, "serial", None),
            stream_uri=stream_uri,
            detections=detections,
            channels=channel_rows,
            metrics=metrics,
        )
    except Exception as exc:
        LOGGER.info("Reolink probe failed for %s: %s", camera["host"], exc)
        return CameraSnapshot("warn", f"Reolink-Status konnte nicht abgefragt werden: {exc}")
    finally:
        for close_method in ("logout", "close", "disconnect"):
            try:
                await _call_if_available(host_api, close_method)
            except Exception:
                LOGGER.debug("Reolink close method failed: %s", close_method, exc_info=True)
        try:
            await _call_if_available(host_api, "expire_session", False)
        except Exception:
            LOGGER.debug("Reolink session close failed", exc_info=True)


async def monitor_events(camera: dict[str, Any], callback: DetectionCallback) -> None:
    """Listen for Reolink TCP push events and publish fresh detection states.

    The regular camera probe is intentionally retained as a fallback.  Push
    events prevent short motion alarms from disappearing between poll cycles.
    """
    try:
        from reolink_aio.api import Host
    except ImportError as exc:
        raise RuntimeError("Reolink-AIO ist nicht installiert") from exc

    http_port = int(camera.get("http_port") or 80)
    host_api = Host(
        camera["host"],
        camera["username"],
        camera["password"],
        port=http_port,
        use_https=http_port == 443,
        timeout=8,
    )
    callback_key = f"tbc-camera-{camera['id']}"
    pending: set[asyncio.Task[Any]] = set()
    loop = asyncio.get_running_loop()

    def callback_finished(task: asyncio.Task[Any]) -> None:
        pending.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            LOGGER.exception("Async Reolink event callback failed for camera %s", camera.get("id"))

    def publish_current_state() -> None:
        channels = list(getattr(host_api, "channels", None) or [0])
        multiple_channels = len(channels) > 1
        detections = [
            row
            for channel in channels
            for row in _channel_rows(host_api, channel, multiple_channels=multiple_channels)
        ]
        try:
            result = callback(detections)
        except Exception:
            LOGGER.exception("Reolink event callback failed for camera %s", camera.get("id"))
            return
        if inspect.isawaitable(result):
            task = asyncio.create_task(result)
            pending.add(task)
            task.add_done_callback(callback_finished)

    def event_received() -> None:
        # reolink-aio currently invokes callbacks in the event loop, but using
        # call_soon_threadsafe keeps this safe if the transport changes later.
        loop.call_soon_threadsafe(publish_current_state)

    baichuan = None
    try:
        await _call_if_available(host_api, "get_host_data")
        await _call_if_available(host_api, "get_states")
        baichuan = getattr(host_api, "baichuan", None)
        if baichuan is None:
            raise RuntimeError("Diese Reolink-Kamera bietet keine TCP-Ereignisse an")
        register = getattr(baichuan, "register_callback", None)
        subscribe = getattr(baichuan, "subscribe_events", None)
        if not callable(register) or not callable(subscribe):
            raise RuntimeError("Reolink TCP-Ereignisse werden nicht unterstützt")
        register(callback_key, event_received)
        await subscribe()
        publish_current_state()
        await asyncio.Future()
    finally:
        unregister = getattr(baichuan, "unregister_callback", None) if baichuan is not None else None
        if callable(unregister):
            unregister(callback_key)
        try:
            await _call_if_available(baichuan, "unsubscribe_events")
        except Exception:
            LOGGER.debug("Reolink event unsubscribe failed", exc_info=True)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for close_method in ("logout", "close", "disconnect"):
            try:
                await _call_if_available(host_api, close_method)
            except Exception:
                LOGGER.debug("Reolink event connection close failed", exc_info=True)


async def _performance_metrics(host_api: Any) -> dict[str, int | float]:
    """Read optional Reolink device performance counters.

    GetPerformance is not implemented by every model/firmware. An unsupported
    or malformed response is therefore treated as unavailable telemetry and
    must never fail the normal camera probe.
    """
    try:
        response = await _call_if_available(host_api, "send", [{"cmd": "GetPerformance"}])
    except Exception:
        LOGGER.debug("Reolink GetPerformance failed", exc_info=True)
        return {}
    if not isinstance(response, list) or not response:
        return {}
    first = response[0]
    if not isinstance(first, dict) or first.get("code") != 0:
        return {}
    value = first.get("value")
    performance = value.get("Performance") if isinstance(value, dict) else None
    if not isinstance(performance, dict):
        return {}

    fields = {
        "cpu_used": "cpuUsed",
        "codec_rate": "codecRate",
        "net_throughput": "netThroughput",
    }
    metrics: dict[str, int | float] = {}
    for target, source in fields.items():
        raw = performance.get(source)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        metrics[target] = raw
    return metrics


def _channel_rows(host_api: Any, channel: int, *, multiple_channels: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for definition in definitions():
        key = f"ch{channel}:{definition.key}" if multiple_channels else definition.key
        label = f"Kanal {channel + 1}: {definition.label}" if multiple_channels else definition.label
        supported = _is_supported(host_api, channel, definition)
        active = _is_active(host_api, channel, definition) if supported else False
        rows.append(
            {
                "key": key,
                "label": label,
                "category": definition.category,
                "channel": channel,
                "supported": supported,
                "active": active,
                "source": "reolink-aio" if supported else "reolink-aio/capability",
                "last_seen": None,
                "raw_value": json.dumps({"supported": supported, "active": active}, default=str),
            }
        )
    return rows


def _is_supported(host_api: Any, channel: int, definition: DetectionDefinition) -> bool:
    if definition.key == "motion":
        return bool(_call_value(host_api, "supported", channel, "motion_detection"))
    if definition.key == "visitor":
        return bool(_call_value(host_api, "is_doorbell", channel))
    if definition.key == "io_input":
        baichuan = getattr(host_api, "baichuan", None)
        return bool(baichuan and _call_value(baichuan, "io_inputs", channel))
    if definition.smart_type:
        return _smart_ai_supported(host_api, channel, definition)
    if definition.capability_key:
        direct = _call_value(host_api, "supported", channel, definition.capability_key)
        if direct is not None:
            return bool(direct)
    if definition.object_type:
        return bool(_call_value(host_api, "ai_supported", channel, definition.object_type))
    return False


def _is_active(host_api: Any, channel: int, definition: DetectionDefinition) -> bool:
    if definition.key == "motion":
        return bool(_call_value(host_api, "motion_detected", channel))
    if definition.key == "visitor":
        return bool(_call_value(host_api, "visitor_detected", channel))
    if definition.key == "sleep":
        return bool(_call_value(host_api, "sleeping", channel))
    if definition.key == "io_input":
        baichuan = getattr(host_api, "baichuan", None)
        inputs = _call_value(baichuan, "io_inputs", channel) if baichuan else []
        if inputs:
            return any(bool(_call_value(baichuan, "io_input_state", channel, index)) for index in inputs)
        return False
    if definition.smart_type:
        baichuan = getattr(host_api, "baichuan", None)
        if not baichuan:
            return False
        for location in _smart_locations(baichuan, channel, definition.smart_type):
            if definition.smart_object:
                if bool(_call_value(baichuan, "smart_ai_state", channel, definition.smart_type, location, definition.smart_object)):
                    return True
            elif bool(_call_value(baichuan, "smart_ai_state", channel, definition.smart_type, location)):
                return True
        return False
    if definition.object_type:
        return bool(_call_value(host_api, "ai_detected", channel, definition.object_type))
    return False


def _smart_ai_supported(host_api: Any, channel: int, definition: DetectionDefinition) -> bool:
    baichuan = getattr(host_api, "baichuan", None)
    if not baichuan:
        return False
    capability_map = {
        "crossline": "ai_crossline",
        "intrusion": "ai_intrusion",
        "loitering": "ai_linger",
        "legacy": "ai_forgotten_item",
        "loss": "ai_taken_item",
    }
    capability_key = capability_map.get(definition.smart_type or "")
    if capability_key and not bool(_call_value(host_api, "supported", channel, capability_key)):
        return False
    locations = _smart_locations(baichuan, channel, definition.smart_type or "")
    if not locations:
        return False
    if not definition.smart_object:
        return True
    for location in locations:
        type_list = _call_value(baichuan, "smart_ai_type_list", channel, definition.smart_type, location) or []
        if definition.smart_object in type_list:
            return True
    return False


def _smart_locations(baichuan: Any, channel: int, smart_type: str) -> list[int]:
    locations = _call_value(baichuan, "smart_location_list", channel, smart_type) or []
    try:
        return list(locations)
    except TypeError:
        return []


async def _rtsp_stream_uri(host_api: Any, channel: int) -> str | None:
    for stream in ("sub", "main"):
        uri = await _call_if_available(host_api, "get_rtsp_stream_source", channel, stream, False)
        if uri:
            return str(uri)
    for stream in ("sub", "main"):
        uri = await _call_if_available(host_api, "get_stream_source", channel, stream, False)
        if uri and str(uri).startswith("rtsp://"):
            return str(uri)
    return None


async def _call_if_available(target: Any, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    result = method(*args)
    if inspect.isawaitable(result):
        return await result
    return result


def _call_value(target: Any, method_name: str, *args: Any) -> Any:
    if target is None:
        return None
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    try:
        return method(*args)
    except Exception:
        LOGGER.debug("Reolink value call failed: %s", method_name, exc_info=True)
        return None


def _safe_camera_value(host_api: Any, method_name: str, channel: int | None) -> str | None:
    value = _call_value(host_api, method_name, channel)
    return str(value) if value not in (None, "") else None


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None
