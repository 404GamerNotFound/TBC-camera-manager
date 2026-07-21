from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

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


@dataclass(frozen=True)
class OnvifEventNotification:
    detection_key: str
    active: bool


def _find_state_value(node: Any) -> str | None:
    """Best-effort search for the boolean SimpleItem ONVIF motion/analytics events
    report their state as (Name="State", Value="true"/"false") - per the ONVIF
    core spec's tt:Message/Data/SimpleItem convention almost every Profile S
    event (cell motion, tamper, field detector, ...) follows."""
    if isinstance(node, dict):
        name = node.get("Name")
        if isinstance(name, str) and name.strip().lower() == "state":
            value = node.get("Value")
            if value is not None:
                return str(value)
        for child in node.values():
            found = _find_state_value(child)
            if found is not None:
                return found
        return None
    if isinstance(node, (list, tuple, set)):
        for child in node:
            found = _find_state_value(child)
            if found is not None:
                return found
        return None
    return None


def parse_pullpoint_notification(message: Any) -> list[OnvifEventNotification]:
    """Best-effort decode of one ONVIF wsnt:NotificationMessage into zero or more
    detection state changes.

    Tolerant by design, like detect_event_keys above: camera firmwares serialize
    topics and message payloads slightly differently, so this walks the whole
    structure collecting text tokens rather than assuming one exact shape. A
    notification whose topic doesn't map to any canonical detection_key yields
    nothing; one without an explicit State SimpleItem is treated as an active
    pulse (matching one-shot event topics like tampering alerts that don't
    carry a boolean state at all).
    """
    serialized = _serialize(message)
    keys = detect_event_keys(serialized)
    if not keys:
        return []
    state_text = _find_state_value(serialized)
    active = state_text is None or state_text.strip().lower() in {"true", "1"}
    return [OnvifEventNotification(detection_key=key, active=active) for key in keys]


@dataclass
class _PullPointStateTracker:
    """Same active/inactive hysteresis as the local-AI ActiveObjectTracker
    (detection/supervisor.py): a key stays "active" for active_timeout_seconds
    after its last True sighting, so a single missed pull cycle - or a camera
    that forgets to send the matching "State=false" notification - doesn't
    flap the reported state forever, or leave it stuck active indefinitely.
    """

    active_timeout_seconds: float = 60.0
    _last_active_at: dict[str, float] = field(default_factory=dict)
    _known_keys: set[str] = field(default_factory=set)

    def update(self, notifications: list[OnvifEventNotification], *, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        for notification in notifications:
            self._known_keys.add(notification.detection_key)
            if notification.active:
                self._last_active_at[notification.detection_key] = now
            else:
                self._last_active_at.pop(notification.detection_key, None)

    def active_keys(self, *, now: float | None = None) -> set[str]:
        now = now if now is not None else time.time()
        return {
            key
            for key, last_active_at in self._last_active_at.items()
            if now - last_active_at <= self.active_timeout_seconds
        }


def _build_onvif_camera(camera: dict[str, Any]) -> Any:
    from onvif import ONVIFCamera

    camera_options = {
        "no_cache": True,
        "encrypt": True,
        "adjust_time": True,
        "event_pullpoint": False,
        "override_camera_address": True,
    }
    parameters = inspect.signature(ONVIFCamera).parameters
    accepts_options = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
    supported_options = {key: value for key, value in camera_options.items() if accepts_options or key in parameters}
    return ONVIFCamera(
        camera["host"],
        int(camera.get("onvif_port") or 80),
        camera["username"],
        camera["password"],
        **supported_options,
    )


async def monitor_events(
    camera: dict[str, Any],
    on_detections: Callable[[list[dict[str, Any]]], None],
    *,
    pull_timeout_seconds: int = 20,
    active_timeout_seconds: float = 60.0,
) -> None:
    """Long-lived ONVIF WS-BaseNotification PullPoint subscription.

    Reports detection state changes to on_detections as they arrive in
    real time, instead of the camera only ever being re-probed periodically.
    Raises if the camera/library doesn't support this at all - the caller
    (main._monitor_camera_events) retries with its own backoff, and a camera
    that simply has no events to report for a while is normal and keeps
    looping rather than raising.
    """
    try:
        from onvif import ONVIFCamera  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(f"ONVIF library is not installed: {exc}") from exc

    onvif_camera = await asyncio.to_thread(_build_onvif_camera, camera)
    pullpoint = await asyncio.to_thread(onvif_camera.create_pullpoint_service)
    tracker = _PullPointStateTracker(active_timeout_seconds=active_timeout_seconds)
    try:
        while True:
            response = await asyncio.to_thread(
                pullpoint.PullMessages,
                {"Timeout": timedelta(seconds=pull_timeout_seconds), "MessageLimit": 100},
            )
            messages = getattr(response, "NotificationMessage", None) or []
            notifications: list[OnvifEventNotification] = []
            for message in messages:
                try:
                    notifications.extend(parse_pullpoint_notification(message))
                except Exception:
                    LOGGER.debug("Could not parse one ONVIF PullPoint notification", exc_info=True)
            if notifications:
                tracker.update(notifications)
                active_keys = tracker.active_keys()
                on_detections(
                    [
                        {"key": notification.detection_key, "active": notification.detection_key in active_keys}
                        for notification in notifications
                    ]
                )
    finally:
        try:
            events_service = getattr(onvif_camera, "event", None) or onvif_camera.create_events_service()
            await asyncio.to_thread(events_service.Unsubscribe)
        except Exception:
            LOGGER.debug("ONVIF PullPoint unsubscribe failed (camera may already be offline)", exc_info=True)
