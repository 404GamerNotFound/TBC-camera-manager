from __future__ import annotations

import shutil
import socket
import subprocess
from pathlib import Path

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
