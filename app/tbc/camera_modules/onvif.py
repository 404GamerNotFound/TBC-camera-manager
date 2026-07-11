from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .detections import normalize_detection_key

LOGGER = logging.getLogger(__name__)


@dataclass
class OnvifProbe:
    success: bool
    message: str
    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    serial: str | None = None
    stream_uris: list[str] = field(default_factory=list)
    event_detection_keys: set[str] = field(default_factory=set)
    raw_events: str | None = None


def _serialize(value: Any) -> Any:
    try:
        from zeep.helpers import serialize_object

        return serialize_object(value)
    except Exception:
        return value


def _collect_text(value: Any, collector: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            collector.append(str(key))
            _collect_text(child, collector)
        return
    if isinstance(value, (list, tuple, set)):
        for child in value:
            _collect_text(child, collector)
        return
    collector.append(str(value))


def detect_event_keys(raw_event_payload: Any) -> set[str]:
    tokens: list[str] = []
    _collect_text(_serialize(raw_event_payload), tokens)
    keys: set[str] = set()
    for token in tokens:
        key = normalize_detection_key([token])
        if key:
            keys.add(key)
    joined_key = normalize_detection_key(tokens)
    if joined_key:
        keys.add(joined_key)
    return keys


def probe_onvif(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    timeout_seconds: int = 8,
) -> OnvifProbe:
    try:
        from onvif import ONVIFCamera
    except ImportError as exc:
        return OnvifProbe(False, f"ONVIF-Bibliothek ist nicht installiert: {exc}")

    try:
        camera = ONVIFCamera(host, port, username, password, no_cache=True, encrypt=False)
        camera.update_xaddrs()
        device_service = camera.create_devicemgmt_service()
        info = device_service.GetDeviceInformation()
        info_data = _serialize(info)

        stream_uris: list[str] = []
        try:
            media_service = camera.create_media_service()
            profiles = media_service.GetProfiles()
            for profile in profiles:
                uri_response = media_service.GetStreamUri(
                    {
                        "StreamSetup": {
                            "Stream": "RTP-Unicast",
                            "Transport": {"Protocol": "RTSP"},
                        },
                        "ProfileToken": profile.token,
                    }
                )
                uri = getattr(uri_response, "Uri", None)
                if uri:
                    stream_uris.append(uri)
        except Exception as exc:
            LOGGER.info("ONVIF media probe failed for %s:%s: %s", host, port, exc)

        event_keys: set[str] = set()
        raw_events: str | None = None
        try:
            events_service = camera.create_events_service()
            event_properties = events_service.GetEventProperties()
            serialized_events = _serialize(event_properties)
            raw_events = json.dumps(serialized_events, default=str)[:8000]
            event_keys = detect_event_keys(serialized_events)
        except Exception as exc:
            LOGGER.info("ONVIF event probe failed for %s:%s: %s", host, port, exc)

        return OnvifProbe(
            success=True,
            message="ONVIF-Verbindung erfolgreich",
            manufacturer=_field(info_data, "Manufacturer"),
            model=_field(info_data, "Model"),
            firmware=_field(info_data, "FirmwareVersion"),
            serial=_field(info_data, "SerialNumber"),
            stream_uris=stream_uris,
            event_detection_keys=event_keys,
            raw_events=raw_events,
        )
    except Exception as exc:
        return OnvifProbe(False, f"ONVIF-Verbindung fehlgeschlagen: {exc}")


def _field(data: Any, name: str) -> str | None:
    if isinstance(data, dict):
        value = data.get(name)
        return str(value) if value not in (None, "") else None
    value = getattr(data, name, None)
    return str(value) if value not in (None, "") else None
