from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time as time_module
from datetime import datetime
from pathlib import Path
from typing import Any

from . import database


def run_health_checks(database_path: str) -> None:
    for camera in database.list_cameras(database_path):
        status = "ok" if camera.get("last_probe_status") == "ok" else "error"
        message = camera.get("last_probe_message") or "Noch keine Prüfung"
        database.upsert_health_status(
            database_path,
            component_type="camera",
            component_id=str(camera["id"]),
            status=status,
            message=f"{camera['name']}: {message}",
        )
        if not camera.get("stream_uri"):
            database.upsert_health_status(
                database_path,
                component_type="stream",
                component_id=str(camera["id"]),
                status="warning",
                message=f"{camera['name']}: kein Stream bekannt",
            )
        else:
            stream_status, stream_message = _probe_stream(str(camera["stream_uri"]))
            database.upsert_health_status(
                database_path,
                component_type="stream",
                component_id=str(camera["id"]),
                status=stream_status,
                message=f"{camera['name']}: {stream_message}",
            )

    for target in database.list_storage_targets(database_path):
        if target["kind"] != "local":
            database.upsert_health_status(
                database_path,
                component_type="storage",
                component_id=str(target["id"]),
                status="ok",
                message=f"{target['name']}: Cloud-Ziel konfiguriert",
            )
            continue
        path = Path(target.get("local_path") or "/recordings")
        try:
            path.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(path)
            free_ratio = usage.free / usage.total if usage.total else 0
            database.upsert_health_status(
                database_path,
                component_type="storage",
                component_id=str(target["id"]),
                status="warning" if free_ratio < 0.1 else "ok",
                message=f"{target['name']}: {usage.free // (1024**3)} GB frei",
            )
        except Exception as exc:
            database.upsert_health_status(
                database_path,
                component_type="storage",
                component_id=str(target["id"]),
                status="error",
                message=f"{target['name']}: {exc}",
            )

    mqtt_config = database.get_mqtt_config(database_path)
    if int(mqtt_config.get("enabled") or 0) != 1:
        database.upsert_health_status(database_path, component_type="mqtt", component_id="broker", status="warning", message="MQTT deaktiviert")
    else:
        try:
            with socket.create_connection((mqtt_config.get("host"), int(mqtt_config.get("port") or 1883)), timeout=5):
                pass
            database.upsert_health_status(database_path, component_type="mqtt", component_id="broker", status="ok", message="Broker erreichbar")
        except Exception as exc:
            database.upsert_health_status(database_path, component_type="mqtt", component_id="broker", status="error", message=str(exc))


def current_system_usage(sample_seconds: float = 0.1) -> dict[str, Any]:
    cpu_percent = _current_cpu_percent(sample_seconds)
    memory = _read_proc_memory()
    load_average = _load_average()
    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cpu_percent": cpu_percent,
        "cpu_label": _format_percent(cpu_percent),
        "cpu_cores": os.cpu_count() or 1,
        "load_label": _format_load_average(load_average),
        "memory_percent": memory["percent"] if memory else None,
        "memory_label": _format_percent(memory["percent"] if memory else None),
        "memory_used_mb": memory["used_mb"] if memory else None,
        "memory_total_mb": memory["total_mb"] if memory else None,
        "memory_detail": _format_memory_detail(memory),
    }


def _probe_stream(stream_uri: str) -> tuple[str, str]:
    if shutil.which("ffprobe") is None:
        return "warning", "ffprobe nicht installiert; Stream URI vorhanden"
    command = [
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        stream_uri,
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=8)
    except subprocess.TimeoutExpired:
        return "error", "Stream-Pruefung Timeout"
    if result.returncode == 0 and "video" in result.stdout:
        return "ok", "Stream lesbar"
    message = (result.stderr or result.stdout or "Stream nicht lesbar").strip().splitlines()
    return "error", message[-1] if message else "Stream nicht lesbar"


def _current_cpu_percent(sample_seconds: float) -> float | None:
    first = _read_proc_cpu_totals()
    if first is not None:
        time_module.sleep(max(0, sample_seconds))
        second = _read_proc_cpu_totals()
        if second is not None:
            return _cpu_percent_from_totals(first, second)
    load_average = _load_average()
    if not load_average:
        return None
    cores = max(1, os.cpu_count() or 1)
    return round(min(100.0, max(0.0, (load_average[0] / cores) * 100)), 1)


def _read_proc_cpu_totals(stat_path: Path = Path("/proc/stat")) -> tuple[int, int] | None:
    try:
        first_line = stat_path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    parts = first_line.split()
    if not parts or parts[0] != "cpu":
        return None
    try:
        values = [int(value) for value in parts[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def _cpu_percent_from_totals(first: tuple[int, int], second: tuple[int, int]) -> float | None:
    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    used_percent = (1 - (idle_delta / total_delta)) * 100
    return round(min(100.0, max(0.0, used_percent)), 1)


def _read_proc_memory(meminfo_path: Path = Path("/proc/meminfo")) -> dict[str, float | int] | None:
    try:
        lines = meminfo_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    values: dict[str, int] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        parts = raw_value.strip().split()
        if not parts:
            continue
        try:
            values[key] = int(parts[0])
        except ValueError:
            continue
    total_kb = values.get("MemTotal")
    available_kb = values.get("MemAvailable", values.get("MemFree"))
    if not total_kb or available_kb is None:
        return None
    used_kb = max(0, total_kb - available_kb)
    return {
        "percent": round((used_kb / total_kb) * 100, 1),
        "used_mb": round(used_kb / 1024),
        "total_mb": round(total_kb / 1024),
        "available_mb": round(available_kb / 1024),
    }


def _load_average() -> tuple[float, float, float] | None:
    try:
        return os.getloadavg()
    except (AttributeError, OSError):
        return None


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}%"


def _format_load_average(load_average: tuple[float, float, float] | None) -> str:
    if not load_average:
        return "Load n/a"
    return f"Load {load_average[0]:.2f}, {load_average[1]:.2f}, {load_average[2]:.2f}"


def _format_memory_detail(memory: dict[str, float | int] | None) -> str:
    if not memory:
        return "Keine RAM-Daten verfügbar"
    used_gb = float(memory["used_mb"]) / 1024
    total_gb = float(memory["total_mb"]) / 1024
    return f"{used_gb:.1f} von {total_gb:.1f} GB belegt"
