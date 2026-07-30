from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

LOGGER = logging.getLogger(__name__)

PTZ_COMMANDS = frozenset(
    {"Stop", "Left", "Right", "Up", "Down", "LeftUp", "LeftDown", "RightUp", "RightDown", "ZoomInc", "ZoomDec"}
)

PTZ_PAN_TILT: dict[str, tuple[float, float]] = {
    "Up": (0.0, 1.0),
    "Down": (0.0, -1.0),
    "Left": (-1.0, 0.0),
    "Right": (1.0, 0.0),
    "LeftUp": (-1.0, 1.0),
    "LeftDown": (-1.0, -1.0),
    "RightUp": (1.0, 1.0),
    "RightDown": (1.0, -1.0),
}
PTZ_ZOOM: dict[str, float] = {"ZoomInc": 1.0, "ZoomDec": -1.0}


def _camera(host: str, port: int, username: str, password: str) -> Any:
    from onvif import ONVIFCamera

    return ONVIFCamera(host, port, username, password, no_cache=True, encrypt=True, adjust_time=True)


def _profile_token(camera: Any) -> str | None:
    profiles = camera.create_media_service().GetProfiles()
    return profiles[0].token if profiles else None


def ptz_capability(*, host: str, port: int, username: str, password: str) -> dict[str, Any]:
    """Probe whether the camera's ONVIF media profile advertises PTZ support.

    Many consumer cameras (TP-Link/Tapo among them) only expose PTZ on some
    models/firmwares; a plain device probe does not reveal this, so a
    dedicated PTZ-configuration lookup is required.
    """
    try:
        camera = _camera(host, port, username, password)
        token = _profile_token(camera)
        if token is None:
            return {"ptz_supported": False}
        configurations = camera.create_ptz_service().GetConfigurations()
        return {"ptz_supported": bool(configurations)}
    except Exception as exc:
        LOGGER.info("ONVIF PTZ capability probe failed for %s:%s: %s", host, port, exc)
        return {"ptz_supported": False}


def _preset_name(preset: Any, index: int) -> str:
    return getattr(preset, "Name", None) or f"Preset {index + 1}"


def ptz_presets(*, host: str, port: int, username: str, password: str) -> dict[str, str]:
    """Return {preset name: preset token} for cameras that support ONVIF PTZ presets.

    Camera-side presets (GetPresets) are distinct from the fixed pan/tilt/zoom
    directions in PTZ_COMMANDS; not every ONVIF PTZ camera supports them, so
    failures degrade to "no presets" rather than surfacing an error.
    """
    try:
        camera = _camera(host, port, username, password)
        token = _profile_token(camera)
        if token is None:
            return {}
        presets = camera.create_ptz_service().GetPresets({"ProfileToken": token}) or []
        return {_preset_name(preset, index): preset.token for index, preset in enumerate(presets)}
    except Exception as exc:
        LOGGER.info("ONVIF PTZ preset probe failed for %s:%s: %s", host, port, exc)
        return {}


def ptz_goto_preset(
    *, host: str, port: int, username: str, password: str, preset_token: str, speed: int | None = None
) -> None:
    camera = _camera(host, port, username, password)
    token = _profile_token(camera)
    if token is None:
        raise RuntimeError("ONVIF: no media profile found for PTZ")
    request: dict[str, Any] = {"ProfileToken": token, "PresetToken": preset_token}
    if speed is not None:
        factor = max(0.1, min(1.0, speed / 100))
        request["Speed"] = {"PanTilt": {"x": factor, "y": factor}, "Zoom": {"x": factor}}
    camera.create_ptz_service().GotoPreset(request)


def ptz_save_preset(*, host: str, port: int, username: str, password: str, name: str) -> str | None:
    camera = _camera(host, port, username, password)
    token = _profile_token(camera)
    if token is None:
        raise RuntimeError("ONVIF: no media profile found for PTZ")
    result = camera.create_ptz_service().SetPreset({"ProfileToken": token, "PresetName": name})
    return result if isinstance(result, str) else getattr(result, "PresetToken", None)


def ptz_remove_preset(*, host: str, port: int, username: str, password: str, preset_token: str) -> None:
    camera = _camera(host, port, username, password)
    token = _profile_token(camera)
    if token is None:
        raise RuntimeError("ONVIF: no media profile found for PTZ")
    camera.create_ptz_service().RemovePreset({"ProfileToken": token, "PresetToken": preset_token})


def ptz_patrol_tours(*, host: str, port: int, username: str, password: str) -> dict[str, Any]:
    """Return patrol/tour support and {tour name: tour token} via ONVIF preset tours.

    Preset tours ("patrol") are a separate, less commonly implemented ONVIF PTZ
    feature from plain presets, so this is probed independently and degrades
    to "not supported" on any failure (missing service, fault response, etc.).
    """
    try:
        camera = _camera(host, port, username, password)
        token = _profile_token(camera)
        if token is None:
            return {"ptz_patrol_supported": False, "ptz_patrol_tours": {}}
        tours = camera.create_ptz_service().GetPresetTours({"ProfileToken": token}) or []
        return {
            "ptz_patrol_supported": True,
            "ptz_patrol_tours": {_preset_name(tour, index): tour.token for index, tour in enumerate(tours)},
        }
    except Exception as exc:
        LOGGER.info("ONVIF PTZ preset-tour probe failed for %s:%s: %s", host, port, exc)
        return {"ptz_patrol_supported": False, "ptz_patrol_tours": {}}


def ptz_operate_tour(
    *, host: str, port: int, username: str, password: str, tour_token: str, operation: str
) -> None:
    camera = _camera(host, port, username, password)
    token = _profile_token(camera)
    if token is None:
        raise RuntimeError("ONVIF: no media profile found for PTZ")
    camera.create_ptz_service().OperatePresetTour(
        {"ProfileToken": token, "PresetTourToken": tour_token, "Operation": operation}
    )


def ptz_move(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    command: str,
    speed: int | None = None,
    pulse_seconds: float = 0.5,
) -> None:
    camera = _camera(host, port, username, password)
    token = _profile_token(camera)
    if token is None:
        raise RuntimeError("ONVIF: no media profile found for PTZ")
    ptz_service = camera.create_ptz_service()

    if command == "Stop":
        ptz_service.Stop({"ProfileToken": token})
        return

    factor = max(0.1, min(1.0, (speed or 50) / 100))
    velocity: dict[str, Any] = {}
    if command in PTZ_ZOOM:
        velocity["Zoom"] = {"x": PTZ_ZOOM[command] * factor}
    elif command in PTZ_PAN_TILT:
        pan, tilt = PTZ_PAN_TILT[command]
        velocity["PanTilt"] = {"x": pan * factor, "y": tilt * factor}
    else:
        raise ValueError(f"Unbekannter PTZ-Befehl: {command}")

    ptz_service.ContinuousMove({"ProfileToken": token, "Velocity": velocity})
    time.sleep(max(0.1, min(3.0, pulse_seconds)))
    try:
        ptz_service.Stop({"ProfileToken": token})
    except Exception:
        LOGGER.debug("ONVIF PTZ stop pulse failed", exc_info=True)


async def get_ptz_control_state(camera: dict[str, Any], *, default_port: int = 80) -> dict[str, Any]:
    """CameraModule.get_control_state() shape for modules that only offer ONVIF PTZ.

    Shared by every ONVIF-based module (TP-Link/Tapo, Standard ONVIF, Aqara):
    none of them expose floodlight/PIR/siren/reboot/battery over plain ONVIF,
    so those fields are always reported as unsupported.
    """
    host = camera["host"]
    port = int(camera.get("onvif_port") or default_port)
    username = camera["username"]
    password = camera["password"]
    result = await asyncio.to_thread(ptz_capability, host=host, port=port, username=username, password=password)
    ptz_supported = bool(result.get("ptz_supported"))
    presets: dict[str, str] = {}
    patrol: dict[str, Any] = {"ptz_patrol_supported": False, "ptz_patrol_tours": {}}
    if ptz_supported:
        presets = await asyncio.to_thread(ptz_presets, host=host, port=port, username=username, password=password)
        patrol = await asyncio.to_thread(
            ptz_patrol_tours, host=host, port=port, username=username, password=password
        )
    return {
        "ptz_supported": ptz_supported,
        "ptz_presets": presets,
        "ptz_patrol_supported": patrol["ptz_patrol_supported"],
        "ptz_patrol_tours": patrol["ptz_patrol_tours"],
        "floodlight_supported": False,
        "floodlight_state": None,
        "pir_supported": False,
        "pir_enabled": None,
        "reboot_supported": False,
        "siren_supported": False,
        "is_battery": False,
        "battery_percentage": None,
        "battery_temperature": None,
        "battery_status": None,
    }


async def send_ptz_control(camera: dict[str, Any], *, action: str, default_port: int = 80, **params: Any) -> dict[str, Any]:
    host = camera["host"]
    port = int(camera.get("onvif_port") or default_port)
    username = camera["username"]
    password = camera["password"]

    if action == "ptz":
        preset_token = str(params.get("preset") or "").strip()
        if preset_token:
            await asyncio.to_thread(
                ptz_goto_preset,
                host=host,
                port=port,
                username=username,
                password=password,
                preset_token=preset_token,
                speed=params.get("speed"),
            )
            return {"status": "ok", "action": action}
        command = str(params.get("command") or "").strip()
        if command not in PTZ_COMMANDS:
            raise ValueError(f"Unbekannter PTZ-Befehl: {command}")
        await asyncio.to_thread(
            ptz_move,
            host=host,
            port=port,
            username=username,
            password=password,
            command=command,
            speed=params.get("speed"),
            pulse_seconds=float(params.get("pulse_seconds") or 0.5),
        )
        return {"status": "ok", "action": action}

    if action == "ptz_preset_save":
        name = str(params.get("name") or "").strip()
        if not name:
            raise ValueError("A preset name is required")
        await asyncio.to_thread(ptz_save_preset, host=host, port=port, username=username, password=password, name=name)
        return {"status": "ok", "action": action}

    if action == "ptz_preset_delete":
        preset_token = str(params.get("preset") or "").strip()
        if not preset_token:
            raise ValueError("A preset is required")
        await asyncio.to_thread(
            ptz_remove_preset, host=host, port=port, username=username, password=password, preset_token=preset_token
        )
        return {"status": "ok", "action": action}

    if action == "ptz_patrol":
        tour_token = str(params.get("tour") or "").strip()
        command = str(params.get("command") or "").strip().lower()
        if not tour_token or command not in ("start", "stop"):
            raise ValueError("A patrol tour and start/stop command are required")
        await asyncio.to_thread(
            ptz_operate_tour,
            host=host,
            port=port,
            username=username,
            password=password,
            tour_token=tour_token,
            operation="Start" if command == "start" else "Stop",
        )
        return {"status": "ok", "action": action}

    raise ValueError(f"This module does not support the action '{action}' via ONVIF")


# --- Onboard motion-detection zones (EXPERIMENTAL) -------------------------------
#
# The ONVIF Rule Engine's CellMotionDetector analytics module exposes a grid
# ("Layout": Columns x Rows) as a standard, typed XML attribute pair, but the
# active-cell bitmap itself is an `xs:any` extension point with no defined wire
# format - vendors are free to encode it however they like. Reading back which
# cells are currently active is not attempted here for that reason. Writing a
# new bitmap uses a row-major "0"/"1" string as the Layout element's content,
# a convention several ONVIF stacks follow in practice, but this is a best
# effort: it may silently have no effect, or raise, on cameras that use a
# different encoding or don't support cell-grid analytics at all. Grid
# discovery (module presence + Columns/Rows) is spec-defined and reliable.
DEFAULT_MOTION_ZONE_COLUMNS = 10
DEFAULT_MOTION_ZONE_ROWS = 10

_CELL_MOTION_DETECTOR_TYPE = "CellMotionDetector"
_LAYOUT_PARAMETER_NAME = "Layout"


def _find_cell_motion_module(analytics_config: Any) -> Any | None:
    engine = getattr(analytics_config, "AnalyticsEngineConfiguration", None)
    for module in getattr(engine, "AnalyticsModule", None) or []:
        if _CELL_MOTION_DETECTOR_TYPE in str(getattr(module, "Type", "")):
            return module
    return None


def _read_cell_layout_size(module: Any) -> tuple[int | None, int | None]:
    parameters = getattr(module, "Parameters", None)
    for item in getattr(parameters, "ElementItem", None) or []:
        if str(getattr(item, "Name", "")) != _LAYOUT_PARAMETER_NAME:
            continue
        layout = getattr(item, "_value_1", item)
        columns = getattr(layout, "Columns", None)
        rows = getattr(layout, "Rows", None)
        try:
            return (
                int(columns) if columns is not None else None,
                int(rows) if rows is not None else None,
            )
        except (TypeError, ValueError):
            return None, None
    return None, None


def motion_zone_capability(*, host: str, port: int, username: str, password: str) -> dict[str, Any]:
    """Probe for an ONVIF CellMotionDetector analytics module and its grid size."""
    try:
        camera = _camera(host, port, username, password)
        media_service = camera.create_media_service()
        for config in media_service.GetVideoAnalyticsConfigurations() or []:
            module = _find_cell_motion_module(config)
            if module is None:
                continue
            columns, rows = _read_cell_layout_size(module)
            return {
                "md_zone_supported": True,
                "md_zone_config_token": config.token,
                "md_zone_columns": columns or DEFAULT_MOTION_ZONE_COLUMNS,
                "md_zone_rows": rows or DEFAULT_MOTION_ZONE_ROWS,
            }
        return {"md_zone_supported": False}
    except Exception as exc:
        LOGGER.info("ONVIF motion-zone capability probe failed for %s:%s: %s", host, port, exc)
        return {"md_zone_supported": False}


def set_motion_zone(
    *, host: str, port: int, username: str, password: str, config_token: str, columns: int, rows: int, cells: str
) -> None:
    """Best-effort write of a new active-cell bitmap to an ONVIF CellMotionDetector.

    Re-fetches and mutates the device's existing analytics configuration in
    place (rather than constructing a fresh one) so any other analytics
    modules or rules already configured on the camera are preserved.
    """
    camera = _camera(host, port, username, password)
    media_service = camera.create_media_service()
    target_config = None
    for config in media_service.GetVideoAnalyticsConfigurations() or []:
        if str(getattr(config, "token", "")) == config_token:
            target_config = config
            break
    if target_config is None:
        raise RuntimeError("This camera no longer reports the expected motion-zone configuration")
    module = _find_cell_motion_module(target_config)
    if module is None:
        raise RuntimeError("This camera no longer reports a cell motion detector module")

    parameters = getattr(module, "Parameters", None)
    layout_item = None
    for item in getattr(parameters, "ElementItem", None) or []:
        if str(getattr(item, "Name", "")) == _LAYOUT_PARAMETER_NAME:
            layout_item = item
            break
    if layout_item is None:
        raise RuntimeError("This camera's cell motion detector does not expose a Layout parameter")

    layout = getattr(layout_item, "_value_1", layout_item)
    try:
        layout.Columns = columns
        layout.Rows = rows
    except Exception as exc:
        raise RuntimeError("This camera's ONVIF stack rejected the motion-zone grid size") from exc
    try:
        layout.Extension = cells
    except Exception:
        LOGGER.info(
            "ONVIF motion-zone bitmap write not supported by this camera's ONVIF stack for %s:%s", host, port
        )

    media_service.SetVideoAnalyticsConfiguration({"Configuration": target_config, "ForcePersistence": True})


async def get_motion_zone_control_state(camera: dict[str, Any], *, default_port: int = 80) -> dict[str, Any]:
    result = await asyncio.to_thread(
        motion_zone_capability,
        host=camera["host"],
        port=int(camera.get("onvif_port") or default_port),
        username=camera["username"],
        password=camera["password"],
    )
    if not result.get("md_zone_supported"):
        return {"md_zone_supported": False}
    return result


async def send_motion_zone_control(camera: dict[str, Any], *, default_port: int = 80, **params: Any) -> dict[str, Any]:
    config_token = str(params.get("config_token") or "").strip()
    cells = str(params.get("cells") or "").strip()
    if not config_token or not cells:
        raise ValueError("A motion-zone configuration and cell grid are required")
    try:
        columns = int(params.get("columns") or 0)
        rows = int(params.get("rows") or 0)
    except (TypeError, ValueError):
        raise ValueError("Invalid motion-zone grid size") from None
    if columns <= 0 or rows <= 0:
        raise ValueError("Invalid motion-zone grid size")
    await asyncio.to_thread(
        set_motion_zone,
        host=camera["host"],
        port=int(camera.get("onvif_port") or default_port),
        username=camera["username"],
        password=camera["password"],
        config_token=config_token,
        columns=columns,
        rows=rows,
        cells=cells,
    )
    return {"status": "ok", "action": "md_zone"}
