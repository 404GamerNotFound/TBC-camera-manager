"""EXPERIMENTAL: ONVIF Media2 privacy masks for ONVIF-based camera modules.

Privacy masking (CreateMask/GetMasks/SetMask/DeleteMask) is exclusively part of
the ONVIF Media2 service (ver20/media/wsdl) - it does not exist in the classic
ver10 Media service, and this project's onvif-zeep dependency has no Media2
support at all (no service factory, no bundled WSDL). This module builds its
own Media2 SOAP client from a locally bundled WSDL + schema closure (see
onvif_media2_schema/, verified to parse and serialize correctly with zeep
without any network access), reusing onvif-zeep's ONVIFService for the actual
SOAP/WS-Security plumbing so authentication matches every other ONVIF call in
this app.

Kept in its own module, deliberately not touched by onvif_control.py's PTZ/
imaging/motion-zone code: this is a much less-trodden path than the rest of
the ONVIF integration (the ONVIF Foundation's own published media2.wsdl and
onvif.xsd do not fully agree with each other at the time of writing), so a
failure here should not be able to affect the well-established parts of ONVIF
support.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

LOGGER = logging.getLogger(__name__)

MEDIA2_NAMESPACE = "http://www.onvif.org/ver20/media/wsdl"
MEDIA2_BINDING = "{http://www.onvif.org/ver20/media/wsdl}Media2Binding"

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "onvif_media2_schema")
_WSDL_PATH = os.path.join(_SCHEMA_DIR, "onvif_media2.wsdl")

DEFAULT_MASK_COLOR = {"X": 0.0, "Y": 0.0, "Z": 0.0, "Colorspace": "http://www.onvif.org/ver10/colorspace/RGB"}


def _camera(host: str, port: int, username: str, password: str) -> Any:
    from onvif import ONVIFCamera

    return ONVIFCamera(host, port, username, password, no_cache=True, encrypt=True, adjust_time=True)


def _media2_xaddr(camera: Any) -> str | None:
    services = camera.devicemgmt.GetServices({"IncludeCapability": False}) or []
    for service in services:
        if str(getattr(service, "Namespace", "")) == MEDIA2_NAMESPACE:
            return str(service.XAddr)
    return None


def _media2_service(camera: Any) -> Any | None:
    if not os.path.isfile(_WSDL_PATH):
        return None
    xaddr = _media2_xaddr(camera)
    if xaddr is None:
        return None
    from onvif.client import ONVIFService

    return ONVIFService(
        xaddr,
        camera.user,
        camera.passwd,
        _WSDL_PATH,
        encrypt=camera.encrypt,
        binding_name=MEDIA2_BINDING,
    )


def _video_source_configuration_token(camera: Any) -> str | None:
    profiles = camera.create_media_service().GetProfiles()
    if not profiles:
        return None
    config = getattr(profiles[0], "VideoSourceConfiguration", None)
    token = getattr(config, "token", None)
    return str(token) if token else None


def _mask_points(polygon: Any) -> list[dict[str, float]]:
    raw_points = getattr(polygon, "Point", None)
    if raw_points is None and isinstance(polygon, dict):
        raw_points = polygon.get("Point")
    points: list[dict[str, float]] = []
    for point in raw_points or []:
        try:
            x = point["x"] if isinstance(point, dict) else point.x
            y = point["y"] if isinstance(point, dict) else point.y
            points.append({"x": float(x), "y": float(y)})
        except (TypeError, KeyError, AttributeError, ValueError):
            continue
    return points


def _mask_fallback_fields(mask: Any, polygon: Any, mask_type: Any, enabled: Any) -> tuple[Any, Any, Any]:
    """Some WSDL/schema combinations leave the named Mask fields unset and put
    raw content in zeep's internal `_value_1` sequence instead - a side effect
    of the Mask type's trailing xs:any extension point. Falls back to scanning
    that sequence by tag/shape when clean attribute access finds nothing."""
    for item in getattr(mask, "_value_1", None) or []:
        if isinstance(item, dict) and "Point" in item:
            polygon = polygon if polygon is not None else item
            continue
        tag = str(getattr(item, "tag", ""))
        if tag.endswith("}Type") and mask_type is None:
            mask_type = getattr(item, "text", None)
        elif tag.endswith("}Enabled") and enabled is None:
            enabled = getattr(item, "text", None)
    return polygon, mask_type, enabled


def _mask_summary(mask: Any) -> dict[str, Any]:
    polygon = getattr(mask, "Polygon", None)
    mask_type = getattr(mask, "Type", None)
    enabled = getattr(mask, "Enabled", None)
    if polygon is None or mask_type is None or enabled is None:
        polygon, mask_type, enabled = _mask_fallback_fields(mask, polygon, mask_type, enabled)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() == "true"
    return {
        "token": str(getattr(mask, "token", "") or ""),
        "enabled": bool(enabled) if enabled is not None else True,
        "type": str(mask_type) if mask_type is not None else "Color",
        "points": _mask_points(polygon),
    }


def privacy_mask_capability(*, host: str, port: int, username: str, password: str) -> dict[str, Any]:
    try:
        camera = _camera(host, port, username, password)
        config_token = _video_source_configuration_token(camera)
        if config_token is None:
            return {"privacy_mask_supported": False}
        media2 = _media2_service(camera)
        if media2 is None:
            return {"privacy_mask_supported": False}
        masks = media2.GetMasks({"ConfigurationToken": config_token}) or []
        return {
            "privacy_mask_supported": True,
            "privacy_mask_config_token": config_token,
            "privacy_masks": [_mask_summary(mask) for mask in masks],
        }
    except Exception as exc:
        LOGGER.info("ONVIF Media2 privacy-mask capability probe failed for %s:%s: %s", host, port, exc)
        return {"privacy_mask_supported": False}


def create_privacy_mask(
    *, host: str, port: int, username: str, password: str, config_token: str, points: list[dict[str, float]]
) -> str | None:
    if len(points) < 3:
        raise ValueError("A privacy mask needs at least 3 points")
    camera = _camera(host, port, username, password)
    media2 = _media2_service(camera)
    if media2 is None:
        raise RuntimeError("This camera does not support ONVIF Media2 privacy masks")
    mask = {
        "ConfigurationToken": config_token,
        "Polygon": {"Point": [{"x": float(p["x"]), "y": float(p["y"])} for p in points]},
        "Type": "Color",
        "Color": dict(DEFAULT_MASK_COLOR),
        "Enabled": True,
    }
    result = media2.CreateMask({"Mask": mask})
    if isinstance(result, str):
        return result
    token = getattr(result, "Token", None)
    return str(token) if token else None


def delete_privacy_mask(*, host: str, port: int, username: str, password: str, token: str) -> None:
    camera = _camera(host, port, username, password)
    media2 = _media2_service(camera)
    if media2 is None:
        raise RuntimeError("This camera does not support ONVIF Media2 privacy masks")
    media2.DeleteMask({"Token": token})


async def get_privacy_mask_control_state(camera: dict[str, Any], *, default_port: int = 80) -> dict[str, Any]:
    return await asyncio.to_thread(
        privacy_mask_capability,
        host=camera["host"],
        port=int(camera.get("onvif_port") or default_port),
        username=camera["username"],
        password=camera["password"],
    )


async def send_privacy_mask_control(
    camera: dict[str, Any], *, action: str, default_port: int = 80, **params: Any
) -> dict[str, Any]:
    host = camera["host"]
    port = int(camera.get("onvif_port") or default_port)
    username = camera["username"]
    password = camera["password"]

    if action == "privacy_mask_create":
        config_token = str(params.get("config_token") or "").strip()
        points = params.get("points") or []
        if not config_token or len(points) < 3:
            raise ValueError("A configuration token and at least 3 points are required")
        token = await asyncio.to_thread(
            create_privacy_mask,
            host=host,
            port=port,
            username=username,
            password=password,
            config_token=config_token,
            points=points,
        )
        return {"status": "ok", "action": action, "token": token}

    if action == "privacy_mask_delete":
        token = str(params.get("token") or "").strip()
        if not token:
            raise ValueError("A mask token is required")
        await asyncio.to_thread(delete_privacy_mask, host=host, port=port, username=username, password=password, token=token)
        return {"status": "ok", "action": action}

    raise ValueError(f"This module does not support the action '{action}' via ONVIF Media2")
