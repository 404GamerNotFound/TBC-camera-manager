from __future__ import annotations

from typing import Any

from app.tbc import mqtt


def _camera() -> dict[str, Any]:
    return {"id": 7, "name": "Front door", "manufacturer": "Acme", "model": "X1"}


def _enabled_config(**overrides: Any) -> dict[str, Any]:
    config = {
        "enabled": 1,
        "host": "broker.local",
        "port": 1883,
        "username": None,
        "password": None,
        "topic_prefix": "tbc",
        "discovery_prefix": "homeassistant",
        "discovery_enabled": 1,
    }
    config.update(overrides)
    return config


def test_publish_control_state_covers_new_entities(monkeypatch):
    monkeypatch.setattr(mqtt.database, "get_mqtt_config", lambda _path: _enabled_config())
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(mqtt, "_publish_many", lambda _config, messages: captured.extend(messages))

    control_state = {
        "hdr_supported": True,
        "ir_supported": True,
        "daynight_mode": "Auto",
        "daynight_threshold": 40,
        "md_sensitivity_supported": True,
        "md_sensitivity": 25,
        "volume_supported": True,
        "volume": 80,
        "video_codec_main": "h265",
        "image_bright_supported": True,
        "image_brightness": 128,
        "battery_asleep": False,
        "is_battery": True,
        "battery_percentage": 90,
        "ai_sensitivity_rows": [{"ai_type": "person", "label": "Person", "value": 60}],
        "is_doorbell": True,
        "quick_reply_supported": True,
        "quick_reply_options": {42: "I'll be right there"},
    }

    mqtt.publish_control_state("db", _camera(), control_state)

    state_topics = {m["topic"]: m["payload"] for m in captured if m["topic"].endswith("/state")}
    assert state_topics["tbc/camera/7/control/daynight/state"] == "Auto"
    assert state_topics["tbc/camera/7/control/daynight_threshold/state"] == "40"
    assert state_topics["tbc/camera/7/control/md_sensitivity/state"] == "25"
    assert state_topics["tbc/camera/7/control/volume/state"] == "80"
    assert state_topics["tbc/camera/7/control/video_codec_main/state"] == "h265"
    assert state_topics["tbc/camera/7/control/image_bright/state"] == "128"
    assert state_topics["tbc/camera/7/control/battery_asleep/state"] == "OFF"
    assert state_topics["tbc/camera/7/control/ai_sensitivity_person/state"] == "60"
    assert "tbc/camera/7/control/hdr/state" not in state_topics  # no state field known

    discovery_topics = {m["topic"] for m in captured if "/config" in m["topic"]}
    assert "homeassistant/switch/tbc_7_control_hdr/config" in discovery_topics
    assert "homeassistant/button/tbc_7_control_quick_reply_42/config" in discovery_topics


def test_publish_control_state_skips_unsupported_fields(monkeypatch):
    monkeypatch.setattr(mqtt.database, "get_mqtt_config", lambda _path: _enabled_config())
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(mqtt, "_publish_many", lambda _config, messages: captured.extend(messages))

    mqtt.publish_control_state("db", _camera(), {})

    assert captured == []


def test_control_command_params_maps_new_entities():
    assert mqtt._control_command_params("hdr", "ON") == ("hdr", {"state": True})
    assert mqtt._control_command_params("ir_lights", "off") == ("ir_lights", {"enable": False})
    assert mqtt._control_command_params("daynight", "Color") == ("daynight", {"mode": "Color"})
    assert mqtt._control_command_params("daynight_threshold", "40") == (
        "daynight_threshold",
        {"value": 40},
    )
    assert mqtt._control_command_params("md_sensitivity", "30") == ("md_sensitivity", {"value": 30})
    assert mqtt._control_command_params("volume", "55") == ("volume", {"volume": "55"})
    assert mqtt._control_command_params("video_codec_sub", "h264") == (
        "video_codec",
        {"value": "h264", "stream": "sub"},
    )
    assert mqtt._control_command_params("image_bright", "200") == ("image", {"bright": "200"})
    assert mqtt._control_command_params("ai_sensitivity_person", "70") == (
        "ai_sensitivity",
        {"value": 70, "ai_type": "person"},
    )
    assert mqtt._control_command_params("quick_reply_42", "PRESS") == (
        "quick_reply",
        {"file_id": 42},
    )
    assert mqtt._control_command_params("quick_reply_notanumber", "PRESS") == (None, {})
    assert mqtt._control_command_params("daynight_threshold", "abc") == (None, {})
    assert mqtt._control_command_params("unknown_entity", "x") == (None, {})
