from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .detections import normalize_detection_key

LOGGER = logging.getLogger(__name__)


@dataclass
class OnvifStreamProfile:
    """One ONVIF media profile's stream, with just enough metadata to rank
    and group it. `source_token` identifies which physical lens/sensor the
    profile belongs to - multi-lens cameras (e.g. dual/triple-lens models)
    expose one ONVIF VideoSource per lens, each with its own set of
    profiles (typically a "main" and "sub" quality per lens)."""

    uri: str
    profile_token: str | None = None
    source_token: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None

    @property
    def quality_key(self) -> tuple[int, float]:
        """Sort key preferring higher resolution, then higher framerate."""
        return ((self.width or 0) * (self.height or 0), self.fps or 0)


@dataclass
class OnvifProbe:
    success: bool
    message: str
    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    serial: str | None = None
    stream_uris: list[str] = field(default_factory=list)
    stream_profiles: list[OnvifStreamProfile] = field(default_factory=list)
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
        camera_options = {
            "no_cache": True,
            "encrypt": True,
            "adjust_time": True,
            "event_pullpoint": False,
            "override_camera_address": True,
        }
        parameters = inspect.signature(ONVIFCamera).parameters
        accepts_options = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        supported_options = {
            key: value
            for key, value in camera_options.items()
            if accepts_options or key in parameters
        }
        camera = ONVIFCamera(
            host,
            port,
            username,
            password,
            **supported_options,
        )
        device_service = camera.create_devicemgmt_service()
        info = device_service.GetDeviceInformation()
        info_data = _serialize(info)

        stream_profiles: list[OnvifStreamProfile] = []
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
                    stream_profiles.append(_stream_profile_from(profile, uri))
        except Exception as exc:
            LOGGER.info("ONVIF media probe failed for %s:%s: %s", host, port, exc)

        stream_profiles = _best_profile_per_lens(stream_profiles)
        stream_uris = [profile.uri for profile in stream_profiles]

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
            message="ONVIF connection successful",
            manufacturer=_field(info_data, "Manufacturer"),
            model=_field(info_data, "Model"),
            firmware=_field(info_data, "FirmwareVersion"),
            serial=_field(info_data, "SerialNumber"),
            stream_uris=stream_uris,
            stream_profiles=stream_profiles,
            event_detection_keys=event_keys,
            raw_events=raw_events,
        )
    except Exception as exc:
        return OnvifProbe(False, _friendly_error(exc))


def _stream_profile_from(profile: Any, uri: str) -> OnvifStreamProfile:
    """Best-effort extraction of quality/lens metadata from a zeep ONVIF
    Profile object. Every field is optional per the ONVIF spec (and some
    camera/firmware implementations omit them), so every access is
    defensive - a profile missing this metadata still yields a usable
    OnvifStreamProfile, just without a way to rank or group it precisely."""
    video_encoder = getattr(profile, "VideoEncoderConfiguration", None)
    resolution = getattr(video_encoder, "Resolution", None)
    rate_control = getattr(video_encoder, "RateControl", None)
    video_source = getattr(profile, "VideoSourceConfiguration", None)
    return OnvifStreamProfile(
        uri=uri,
        profile_token=getattr(profile, "token", None),
        source_token=getattr(video_source, "SourceToken", None),
        width=getattr(resolution, "Width", None),
        height=getattr(resolution, "Height", None),
        fps=getattr(rate_control, "FrameRateLimit", None),
    )


def _best_profile_per_lens(profiles: list[OnvifStreamProfile]) -> list[OnvifStreamProfile]:
    """Collapse profiles to one per physical lens, keeping only the
    highest-resolution/-framerate profile for each.

    Profiles without a `source_token` (common on single-lens cameras -
    VideoSourceConfiguration is optional in ONVIF's GetProfiles response)
    are all treated as the same, single implicit lens, which is exactly
    today's single-stream behavior for the overwhelming majority of
    cameras. Group order follows first-encounter order so lens indexing
    stays stable across probes of the same camera.
    """
    best_by_lens: dict[str | None, OnvifStreamProfile] = {}
    for candidate in profiles:
        lens_key = candidate.source_token
        current_best = best_by_lens.get(lens_key)
        if current_best is None or candidate.quality_key > current_best.quality_key:
            best_by_lens[lens_key] = candidate
    return list(best_by_lens.values())


def _field(data: Any, name: str) -> str | None:
    if isinstance(data, dict):
        value = data.get(name)
        return str(value) if value not in (None, "") else None
    value = getattr(data, name, None)
    return str(value) if value not in (None, "") else None


def _friendly_error(exc: Exception) -> str:
    message = str(exc)
    if "authority failure" in message.lower() or "notauthorized" in message.lower():
        return "ONVIF sign-in rejected: check the camera username, password, and camera time"
    return f"ONVIF connection failed: {message}"
