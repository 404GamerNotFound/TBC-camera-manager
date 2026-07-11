from __future__ import annotations

import shutil
import subprocess
from urllib.parse import quote, urlsplit, urlunsplit

from ..live import redact_rtsp_credentials


def validate_manual_stream_uri(value: str) -> str:
    """Validate a user-provided RTSP URI without ever logging its credentials."""
    uri = str(value or "").strip()
    if not uri or any(character in uri for character in ("\r", "\n", "\x00")):
        raise ValueError("Eine gültige RTSP-/RTSPS-URL ist erforderlich")
    parsed = urlsplit(uri)
    if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.hostname:
        raise ValueError("Die Stream-URL muss mit rtsp:// oder rtsps:// beginnen und einen Host enthalten")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Die RTSP-/RTSPS-URL enthält einen ungültigen Port") from exc
    return uri


def rtsp_uri_with_credentials(uri: str, username: str, password: str) -> str:
    parsed = urlsplit(str(uri))
    if parsed.scheme.lower() != "rtsp" or not parsed.hostname:
        return str(uri)
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    userinfo = f"{quote(str(username), safe='')}:{quote(str(password), safe='')}@"
    return urlunsplit(("rtsp", f"{userinfo}{host}{port}", parsed.path, parsed.query, parsed.fragment))


def build_rtsp_uri(
    *,
    host: str,
    port: int,
    path: str,
    username: str,
    password: str,
) -> str:
    normalized_host = str(host).strip()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    normalized_path = f"/{str(path).lstrip('/')}"
    userinfo = f"{quote(str(username), safe='')}:{quote(str(password), safe='')}@"
    return f"rtsp://{userinfo}{normalized_host}:{int(port)}{normalized_path}"


def probe_rtsp_stream(stream_uri: str, timeout_seconds: int = 8) -> tuple[str, str]:
    if shutil.which("ffprobe") is None:
        return "warning", "ffprobe nicht installiert; RTSP-Adresse wurde konfiguriert"
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
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return "error", "RTSP-Prüfung hat das Zeitlimit überschritten"
    if result.returncode == 0 and "video" in result.stdout:
        return "ok", "RTSP-Stream erreichbar"
    lines = (result.stderr or result.stdout or "RTSP-Stream nicht erreichbar").strip().splitlines()
    message = lines[-1] if lines else "RTSP-Stream nicht erreichbar"
    return "error", redact_rtsp_credentials(message)
