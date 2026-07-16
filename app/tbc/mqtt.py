from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from . import database
from .camera_modules import CameraCapability, get_camera_module
from .camera_modules.registry import UnknownCameraModuleError

LOGGER = logging.getLogger(__name__)

# Home Assistant MQTT Discovery entities for Reolink camera control functions,
# mirroring neolink.net's HA integration (floodlight/PIR/reboot/siren/battery).
CONTROL_ENTITIES: tuple[dict[str, Any], ...] = (
    {
        "key": "floodlight",
        "component": "light",
        "label": "Floodlight",
        "state_field": "floodlight_state",
        "supported_field": "floodlight_supported",
        "command": True,
        "extra": {"payload_on": "ON", "payload_off": "OFF"},
    },
    {
        "key": "pir",
        "component": "switch",
        "label": "PIR sensor",
        "state_field": "pir_enabled",
        "supported_field": "pir_supported",
        "command": True,
        "extra": {"payload_on": "ON", "payload_off": "OFF", "device_class": "switch"},
    },
    {
        "key": "reboot",
        "component": "button",
        "label": "Restart",
        "state_field": None,
        "supported_field": "reboot_supported",
        "command": True,
        "extra": {"payload_press": "PRESS", "device_class": "restart"},
    },
    {
        "key": "siren",
        "component": "button",
        "label": "Play siren",
        "state_field": None,
        "supported_field": "siren_supported",
        "command": True,
        "extra": {"payload_press": "ON"},
    },
    {
        "key": "battery",
        "component": "sensor",
        "label": "Battery level",
        "state_field": "battery_percentage",
        "supported_field": "is_battery",
        "command": False,
        "extra": {"device_class": "battery", "unit_of_measurement": "%"},
    },
    {
        "key": "ptz_up",
        "component": "button",
        "label": "Schwenken hoch",
        "state_field": None,
        "supported_field": "ptz_supported",
        "command": True,
        "extra": {"payload_press": "PRESS"},
    },
    {
        "key": "ptz_down",
        "component": "button",
        "label": "Schwenken runter",
        "state_field": None,
        "supported_field": "ptz_supported",
        "command": True,
        "extra": {"payload_press": "PRESS"},
    },
    {
        "key": "ptz_left",
        "component": "button",
        "label": "Schwenken links",
        "state_field": None,
        "supported_field": "ptz_supported",
        "command": True,
        "extra": {"payload_press": "PRESS"},
    },
    {
        "key": "ptz_right",
        "component": "button",
        "label": "Schwenken rechts",
        "state_field": None,
        "supported_field": "ptz_supported",
        "command": True,
        "extra": {"payload_press": "PRESS"},
    },
)

PTZ_ENTITY_COMMANDS = {
    "ptz_up": "Up",
    "ptz_down": "Down",
    "ptz_left": "Left",
    "ptz_right": "Right",
}


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


def publish_control_state(database_path: str, camera: dict[str, Any], control_state: dict[str, Any]) -> None:
    config = database.get_mqtt_config(database_path)
    if not _enabled(config):
        return

    messages: list[dict[str, Any]] = []
    prefix = _topic_prefix(config)
    discovery_enabled = int(config.get("discovery_enabled") or 0) == 1
    for entity in CONTROL_ENTITIES:
        if not control_state.get(entity["supported_field"]):
            continue
        state_topic = f"{prefix}/camera/{camera['id']}/control/{entity['key']}/state"
        if entity["state_field"] is not None:
            messages.append(
                {
                    "topic": state_topic,
                    "payload": _control_state_payload(entity, control_state.get(entity["state_field"])),
                    "retain": True,
                }
            )
        if discovery_enabled:
            messages.append(
                {
                    "topic": _control_discovery_topic(config, camera, entity),
                    "payload": json.dumps(_control_discovery_payload(prefix, camera, entity, state_topic)),
                    "retain": True,
                }
            )
    _publish_many(config, messages)


def _control_state_payload(entity: dict[str, Any], value: Any) -> str:
    if entity["component"] == "sensor":
        return "" if value is None else str(value)
    return "ON" if value else "OFF"


def _control_discovery_topic(config: dict[str, Any], camera: dict[str, Any], entity: dict[str, Any]) -> str:
    discovery_prefix = _topic_key(str(config.get("discovery_prefix") or "homeassistant")).strip("/")
    unique_id = f"tbc_{camera['id']}_control_{entity['key']}"
    return f"{discovery_prefix}/{entity['component']}/{unique_id}/config"


def _control_discovery_payload(
    topic_prefix: str,
    camera: dict[str, Any],
    entity: dict[str, Any],
    state_topic: str,
) -> dict[str, Any]:
    unique_id = f"tbc_{camera['id']}_control_{entity['key']}"
    payload: dict[str, Any] = {
        "name": f"{camera.get('name')} {entity['label']}",
        "unique_id": unique_id,
        "availability_topic": f"{topic_prefix}/availability",
        "device": {
            "identifiers": [f"tbc_camera_{camera['id']}"],
            "name": camera.get("name"),
            "manufacturer": camera.get("manufacturer") or "Camera",
            "model": camera.get("model") or "Camera",
        },
        **entity["extra"],
    }
    if entity["state_field"] is not None:
        payload["state_topic"] = state_topic
    if entity["command"]:
        payload["command_topic"] = f"{topic_prefix}/camera/{camera['id']}/control/{entity['key']}/set"
    return payload


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
            "manufacturer": camera.get("manufacturer") or "Camera",
            "model": camera.get("model") or "Camera",
        },
    }


def _topic_key(value: str) -> str:
    value = value.replace(":", "_")
    return re.sub(r"[^a-zA-Z0-9_/-]+", "_", value).strip("_").lower()


_COMMAND_TOPIC_RE = re.compile(r"^(?P<prefix>.+)/camera/(?P<camera_id>\d+)/control/(?P<entity_key>[a-z_]+)/set$")


async def run_control_listener(database_path: str) -> None:
    """Bridge Home Assistant / MQTT command topics to camera control actions.

    Reconnects whenever the broker configuration changes, mirroring the
    reconnect-on-fingerprint-change pattern used for other background
    workers in this app.
    """
    loop = asyncio.get_running_loop()
    client = None
    fingerprint: tuple[Any, ...] | None = None
    try:
        while True:
            config = await asyncio.to_thread(database.get_mqtt_config, database_path)
            new_fingerprint = (
                _enabled(config),
                config.get("host"),
                config.get("port"),
                config.get("username"),
                config.get("password"),
                config.get("topic_prefix"),
            )
            if new_fingerprint != fingerprint:
                if client is not None:
                    await asyncio.to_thread(_stop_client, client)
                    client = None
                fingerprint = new_fingerprint
                if _enabled(config):
                    client = _start_control_client(config, database_path, loop)
            await asyncio.sleep(15)
    finally:
        if client is not None:
            await asyncio.to_thread(_stop_client, client)


def _start_control_client(config: dict[str, Any], database_path: str, loop: asyncio.AbstractEventLoop) -> Any | None:
    try:
        import paho.mqtt.client as mqtt_client
    except ImportError:
        LOGGER.warning("paho-mqtt is not installed; MQTT control listener disabled")
        return None

    prefix = _topic_prefix(config)
    try:
        client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION2,
            client_id="tbc-camera-manager-control",
        )
    except AttributeError:
        client = mqtt_client.Client(client_id="tbc-camera-manager-control")
    if config.get("username"):
        client.username_pw_set(str(config.get("username")), str(config.get("password") or ""))

    def on_connect(cli: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        cli.subscribe(f"{prefix}/camera/+/control/+/set")

    def on_message(cli: Any, userdata: Any, message: Any) -> None:
        match = _COMMAND_TOPIC_RE.match(message.topic)
        if not match or match.group("prefix") != prefix:
            return
        payload = message.payload.decode("utf-8", errors="ignore") if isinstance(message.payload, (bytes, bytearray)) else str(message.payload)
        asyncio.run_coroutine_threadsafe(
            _dispatch_control_command(database_path, int(match.group("camera_id")), match.group("entity_key"), payload),
            loop,
        )

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(str(config["host"]), int(config.get("port") or 1883), keepalive=30)
        client.loop_start()
    except Exception:
        LOGGER.exception("MQTT control listener could not connect")
        return None
    return client


def _stop_client(client: Any) -> None:
    try:
        client.loop_stop()
        client.disconnect()
    except Exception:
        LOGGER.debug("MQTT control listener disconnect failed", exc_info=True)


async def _dispatch_control_command(database_path: str, camera_id: int, entity_key: str, payload: str) -> None:
    camera = database.get_camera(database_path, camera_id)
    if not camera:
        return
    try:
        camera_module = get_camera_module(camera.get("module_key"))
    except UnknownCameraModuleError:
        return
    if not camera_module.supports(CameraCapability.CONTROL):
        return

    action, params = _control_command_params(entity_key, payload)
    if action is None:
        return
    try:
        await camera_module.send_control(camera, action=action, **params)
    except Exception:
        LOGGER.exception("MQTT control command failed for camera %s (%s)", camera_id, entity_key)
        return
    try:
        control_state = await camera_module.get_control_state(camera)
        await asyncio.to_thread(publish_control_state, database_path, camera, control_state)
    except Exception:
        LOGGER.debug("MQTT control state re-publish failed for camera %s", camera_id, exc_info=True)


def _control_command_params(entity_key: str, payload: str) -> tuple[str | None, dict[str, Any]]:
    payload_upper = payload.strip().upper()
    if entity_key == "floodlight":
        return "floodlight", {"state": payload_upper == "ON"}
    if entity_key == "pir":
        return "pir", {"enable": payload_upper == "ON"}
    if entity_key == "reboot":
        return "reboot", {}
    if entity_key == "siren":
        return "siren", {"duration": 5}
    if entity_key in PTZ_ENTITY_COMMANDS:
        return "ptz", {"command": PTZ_ENTITY_COMMANDS[entity_key]}
    return None, {}
