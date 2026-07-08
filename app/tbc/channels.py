from __future__ import annotations

from typing import Any


def apply_channel_enabled_filter(
    detections: list[dict[str, Any]],
    channels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    disabled_channels = {
        int(channel["channel_index"])
        for channel in channels
        if int(channel.get("enabled") or 0) != 1
    }
    if not disabled_channels:
        return detections
    filtered: list[dict[str, Any]] = []
    for detection in detections:
        channel = detection.get("channel")
        if channel is not None and int(channel) in disabled_channels:
            filtered.append({**detection, "active": False})
        else:
            filtered.append(detection)
    return filtered
