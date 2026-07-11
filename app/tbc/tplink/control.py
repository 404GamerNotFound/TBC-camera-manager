from __future__ import annotations

from typing import Any

from ..camera_modules import onvif_control

DEFAULT_ONVIF_PORT = 2020


async def get_control_state(camera: dict[str, Any]) -> dict[str, Any]:
    return await onvif_control.get_ptz_control_state(camera, default_port=DEFAULT_ONVIF_PORT)


async def send_control(camera: dict[str, Any], *, action: str, **params: Any) -> dict[str, Any]:
    return await onvif_control.send_ptz_control(camera, action=action, default_port=DEFAULT_ONVIF_PORT, **params)
