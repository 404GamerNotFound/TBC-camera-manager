from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import database

LOGGER = logging.getLogger(__name__)


def publish_detection_states(database_path: str, camera: dict[str, Any], detections: list[dict[str, Any]]) -> None:
    config = database.get_mqtt_config(database_path)
    if not _enabled(config):
        return

    messages: list[dict[str, Any]] = []
    prefix = _topic_prefix(config)
    for detection in detections:
        key = str(detection.get("key") or "")
        if not key:
            continue
        state_topic = f"{prefix}/camera/{camera['id']}/{_topic_key(key)}/state"
        messages.append(
            {
                "topic": state_topic,
                "payload": "ON" if detection.get("active") else "OFF",
                "retain": True,
            }
        )
        if int(config.get("discovery_enabled") or 0) == 1:
            messages.append(
                {
                    "topic": _discovery_topic(config, camera, detection),
                    "payload": json.dumps(_discovery_payload(prefix, camera, detection, state_topic)),
                    "retain": True,
                }
            )
    _publish_many(config, messages)


def publish_event(
    database_path: str,
    *,
    camera_id: int,
    event_type: str,
    detection_key: str | None,
    payload: str | None,
) -> None:
    config = database.get_mqtt_config(database_path)
    if not _enabled(config):
        return
    camera = database.get_camera(database_path, camera_id)
    if not camera:
        return
    topic = f"{_topic_prefix(config)}/camera/{camera_id}/event"
    _publish_many(
        config,
        [
            {
                "topic": topic,
                "payload": json.dumps(
                    {
                        "camera_id": camera_id,
                        "camera": camera.get("name"),
                        "event_type": event_type,
                        "detection_key": detection_key,
                        "payload": payload,
                    }
                ),
                "retain": False,
            }
        ],
    )


def _enabled(config: dict[str, Any]) -> bool:
    return int(config.get("enabled") or 0) == 1 and bool(config.get("host"))


def _publish_many(config: dict[str, Any], messages: list[dict[str, Any]]) -> None:
    if not messages:
        return
    try:
        import paho.mqtt.publish as publish
    except ImportError:
        LOGGER.warning("paho-mqtt is not installed; MQTT publish skipped")
        return

    auth = None
    if config.get("username"):
        auth = {"username": config.get("username"), "password": config.get("password") or ""}
    try:
        publish.multiple(
            messages,
            hostname=str(config["host"]),
            port=int(config.get("port") or 1883),
            auth=auth,
            client_id="tbc-camera-manager",
        )
    except Exception:
        LOGGER.exception("MQTT publish failed")


def _topic_prefix(config: dict[str, Any]) -> str:
    return _topic_key(str(config.get("topic_prefix") or "tbc")).strip("/") or "tbc"


def _discovery_topic(config: dict[str, Any], camera: dict[str, Any], detection: dict[str, Any]) -> str:
    discovery_prefix = _topic_key(str(config.get("discovery_prefix") or "homeassistant")).strip("/")
    unique_id = f"tbc_{camera['id']}_{_topic_key(str(detection.get('key') or 'event'))}"
    return f"{discovery_prefix}/binary_sensor/{unique_id}/config"


def _discovery_payload(
    topic_prefix: str,
    camera: dict[str, Any],
    detection: dict[str, Any],
    state_topic: str,
) -> dict[str, Any]:
    key = str(detection.get("key") or "event")
    return {
        "name": f"{camera.get('name')} {detection.get('label') or key}",
        "unique_id": f"tbc_{camera['id']}_{_topic_key(key)}",
        "state_topic": state_topic,
        "payload_on": "ON",
        "payload_off": "OFF",
        "device_class": "motion",
        "availability_topic": f"{topic_prefix}/availability",
        "device": {
            "identifiers": [f"tbc_camera_{camera['id']}"],
            "name": camera.get("name"),
            "manufacturer": camera.get("manufacturer") or "Reolink",
            "model": camera.get("model") or "Kamera",
        },
    }


def _topic_key(value: str) -> str:
    value = value.replace(":", "_")
    return re.sub(r"[^a-zA-Z0-9_/-]+", "_", value).strip("_").lower()

