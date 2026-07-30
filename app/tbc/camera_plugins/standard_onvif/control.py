from __future__ import annotations

from typing import Any

from tbc_camera_api import onvif_control, onvif_privacy_mask

DEFAULT_ONVIF_PORT = 80


_IMAGING_ACTIONS = {"image", "daynight", "hdr"}
_PRIVACY_MASK_ACTIONS = {"privacy_mask_create", "privacy_mask_delete"}


async def get_control_state(camera: dict[str, Any]) -> dict[str, Any]:
    state = await onvif_control.get_ptz_control_state(camera, default_port=DEFAULT_ONVIF_PORT)
    state.update(await onvif_control.get_motion_zone_control_state(camera, default_port=DEFAULT_ONVIF_PORT))
    state.update(await onvif_control.get_imaging_control_state(camera, default_port=DEFAULT_ONVIF_PORT))
    state.update(await onvif_privacy_mask.get_privacy_mask_control_state(camera, default_port=DEFAULT_ONVIF_PORT))
    return state


async def send_control(camera: dict[str, Any], *, action: str, **params: Any) -> dict[str, Any]:
    if action == "md_zone":
        return await onvif_control.send_motion_zone_control(camera, default_port=DEFAULT_ONVIF_PORT, **params)
    if action in _IMAGING_ACTIONS:
        return await onvif_control.send_imaging_control(camera, action=action, default_port=DEFAULT_ONVIF_PORT, **params)
    if action in _PRIVACY_MASK_ACTIONS:
        return await onvif_privacy_mask.send_privacy_mask_control(
            camera, action=action, default_port=DEFAULT_ONVIF_PORT, **params
        )
    return await onvif_control.send_ptz_control(camera, action=action, default_port=DEFAULT_ONVIF_PORT, **params)
