from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, AsyncIterator, Callable

LOGGER = logging.getLogger(__name__)

TRIGGER_LABELS = {
    "TIMER": "Zeitplan",
    "MOTION": "Bewegung",
    "VEHICLE": "Fahrzeug",
    "ANIMAL": "Tier",
    "PERSON": "Person",
    "DOORBELL": "Klingel",
    "PACKAGE": "Paket",
    "FACE": "Gesicht",
    "IO": "I/O",
    "CRYING": "Weinen",
    "CROSSLINE": "Linienuebertritt",
    "INTRUSION": "Eindringen",
    "LINGER": "Verweilen",
    "FORGOTTEN_ITEM": "Vergessener Gegenstand",
    "TAKEN_ITEM": "Entfernter Gegenstand",
}


@dataclass
class SdCardDownload:
    filename: str
    length: int
    stream: Any
    release: Callable[[], None]
    host_api: Any

    async def chunks(self, chunk_size: int = 65536) -> AsyncIterator[bytes]:
        try:
            while True:
                chunk = await self.stream.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                self.release()
            finally:
                await _close_host(self.host_api)


async def list_sd_card_recordings(
    camera: dict[str, Any],
    *,
    channel: int,
    start: datetime,
    end: datetime,
    stream: str = "main",
) -> list[dict[str, Any]]:
    host_api = _host(camera)
    try:
        await _call_if_available(host_api, "get_host_data")
        _ensure_stream_channel(host_api, channel)
        _, files = await host_api.request_vod_files(channel=channel, start=start, end=end, stream=_valid_stream(stream))
        return [_vod_file_row(file, channel=channel, stream=_valid_stream(stream)) for file in files]
    except Exception:
        LOGGER.exception("SD card search failed for camera %s", camera.get("id"))
        raise
    finally:
        await _close_host(host_api)


async def open_sd_card_download(
    camera: dict[str, Any],
    *,
    channel: int,
    source: str,
    start_id: str,
    end_id: str,
    stream: str = "main",
) -> SdCardDownload:
    if not source:
        raise ValueError("SD-Card-Datei fehlt")
    host_api = _host(camera)
    try:
        await _call_if_available(host_api, "get_host_data")
        _ensure_stream_channel(host_api, channel)
        filename = source
        kwargs: dict[str, Any] = {}
        if bool(getattr(host_api, "is_nvr", False)):
            if not start_id or not end_id:
                raise ValueError("Fuer NVR-Downloads fehlen Start- oder Endzeit")
            kwargs = {
                "start_time": start_id,
                "end_time": end_id,
                "channel": channel,
                "stream": _valid_stream(stream),
            }
        download = await host_api.download_vod(
            filename=filename,
            wanted_filename=_download_name(source, start_id),
            **kwargs,
        )
        return SdCardDownload(
            filename=str(download.filename),
            length=int(download.length),
            stream=download.stream,
            release=download.close,
            host_api=host_api,
        )
    except Exception:
        await _close_host(host_api)
        LOGGER.exception("SD card download failed for camera %s", camera.get("id"))
        raise RuntimeError(_friendly_reolink_error()) from None


def _host(camera: dict[str, Any]):
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
        timeout=20,
    )


def _ensure_stream_channel(host_api: Any, channel: int) -> None:
    stream_channels = list(getattr(host_api, "stream_channels", None) or getattr(host_api, "channels", None) or [0])
    if channel not in stream_channels:
        raise ValueError(f"Kanal {channel + 1} ist fuer SD-Card-Wiedergabe nicht verfuegbar")


def _vod_file_row(file: Any, *, channel: int, stream: str) -> dict[str, Any]:
    start_time = _safe_value(file, "start_time")
    end_time = _safe_value(file, "end_time")
    duration = _safe_value(file, "duration")
    source = str(_safe_value(file, "file_name") or "")
    return {
        "source": source,
        "file_name": PurePosixPath(source).name or source,
        "channel": channel,
        "stream": stream,
        "start_time": _format_datetime(start_time),
        "end_time": _format_datetime(end_time),
        "start_id": str(_safe_value(file, "start_time_id") or ""),
        "end_id": str(_safe_value(file, "end_time_id") or ""),
        "duration_seconds": int(duration.total_seconds()) if duration is not None else 0,
        "size_bytes": int(_safe_value(file, "size") or 0),
        "trigger_label": _trigger_label(_safe_value(file, "triggers")),
    }


def _trigger_label(trigger: Any) -> str:
    if trigger in (None, 0):
        return "unbekannt"
    labels: list[str] = []
    for name, label in TRIGGER_LABELS.items():
        member = getattr(trigger.__class__, name, None)
        if member is not None and bool(trigger & member):
            labels.append(label)
    return ", ".join(labels) if labels else "unbekannt"


def _format_datetime(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _safe_value(target: Any, name: str) -> Any:
    try:
        return getattr(target, name)
    except Exception:
        LOGGER.debug("Could not read VOD value %s", name, exc_info=True)
        return None


async def _call_if_available(target: Any, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    result = method(*args)
    if inspect.isawaitable(result):
        return await result
    return result


async def _close_host(host_api: Any) -> None:
    try:
        await _call_if_available(host_api, "logout")
    except Exception:
        LOGGER.debug("Could not logout Reolink host", exc_info=True)
    try:
        await _call_if_available(host_api, "expire_session", False)
    except Exception:
        LOGGER.debug("Could not close Reolink host session", exc_info=True)


def _valid_stream(stream: str) -> str:
    return "sub" if stream == "sub" else "main"


def _download_name(source: str, start_id: str) -> str:
    name = PurePosixPath(source).name
    if name:
        return name
    return f"sd-card-{start_id or 'clip'}.mp4"


def _friendly_reolink_error() -> str:
    return (
        "Kamera konnte das SD-Card-Video nicht bereitstellen. "
        "Bitte pruefen, ob der HTTP-Port der Kamera korrekt gesetzt ist und ob die Kamera gerade bereits einen anderen Playback-/Download-Stream bedient."
    )
