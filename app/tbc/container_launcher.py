"""Container entry point for standalone Docker and Home Assistant App use."""

from __future__ import annotations

import json
import os
import pwd
import secrets
import sys
from pathlib import Path
from typing import Any

APP_USER = "tbc"
DEFAULT_OPTIONS_PATH = Path("/data/options.json")
DEFAULT_SECRET_PATH = Path("/data/.tbc-secret-key")
HOME_ASSISTANT_RECORDINGS_PATH = Path("/recordings/tbc-camera-manager")


def load_home_assistant_options(path: Path = DEFAULT_OPTIONS_PATH) -> dict[str, Any] | None:
    """Return Supervisor options, or None when running as a regular container."""

    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Home-Assistant-Konfiguration kann nicht gelesen werden: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Home-Assistant-Konfiguration muss ein JSON-Objekt sein")
    return value


def persistent_secret(path: Path = DEFAULT_SECRET_PATH) -> str:
    """Read or atomically create the stable cookie secret used by the HA App."""

    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        value = secrets.token_urlsafe(48)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return persistent_secret(path)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.write("\n")
    except OSError as exc:
        raise RuntimeError(f"Persistent session key could not be read: {exc}") from exc

    if not value:
        raise RuntimeError("Persistent session key is empty")
    return value


def configure_home_assistant(options: dict[str, Any]) -> None:
    """Translate Supervisor options into TBC's existing environment contract."""

    password = str(options.get("admin_password") or "")
    if not password:
        raise RuntimeError("Die Home-Assistant-Option admin_password muss gesetzt sein")

    os.environ.update(
        {
            "TBC_ADMIN_USERNAME": str(options.get("admin_username") or "admin"),
            "TBC_ADMIN_PASSWORD": password,
            "TBC_SECRET_KEY": persistent_secret(),
            "TBC_DATABASE_PATH": "/data/tbc.sqlite3",
            "TBC_PLUGIN_SITE_PACKAGES_PATH": "/data/plugin-site-packages",
            "TBC_RECORDINGS_PATH": str(HOME_ASSISTANT_RECORDINGS_PATH),
            "TBC_CAMERA_MODULES_PATH": "/data/camera-modules",
            "TBC_THEME_MODULES_PATH": "/data/design-themes",
            "TBC_CLOUD_MODULES_PATH": "/data/cloud-modules",
            "TBC_DASHBOARD_SNAPSHOTS_PATH": "/data/dashboard-snapshots",
            "TBC_DETECTION_MODELS_PATH": "/data/detection-models",
            "TBC_DASHBOARD_SNAPSHOT_INTERVAL_SECONDS": str(
                options.get("dashboard_snapshot_interval_seconds") or 600
            ),
            "TBC_POLL_INTERVAL_SECONDS": str(options.get("poll_interval_seconds") or 60),
            "TBC_PUBLIC_BASE_URL": str(options.get("public_base_url") or ""),
            "TBC_PORT": "8732",
        }
    )


def prepare_runtime_paths(home_assistant: bool) -> None:
    """Create writable paths before dropping container root privileges."""

    data_path = Path(os.environ.get("TBC_DATABASE_PATH", "/data/tbc.sqlite3")).parent
    recordings_path = Path(os.environ.get("TBC_RECORDINGS_PATH", "/recordings"))
    plugin_packages_path = Path(os.environ.get("TBC_PLUGIN_SITE_PACKAGES_PATH", data_path / "plugin-site-packages"))
    for path in (data_path, recordings_path, plugin_packages_path):
        path.mkdir(parents=True, exist_ok=True)

    if os.geteuid() != 0:
        return

    # /data is private to this app. The mapped Home Assistant media directory is
    # shared, so only the dedicated TBC child directory is ever re-owned.
    account = pwd.getpwnam(APP_USER)
    paths_to_own = [data_path, plugin_packages_path]
    if home_assistant:
        paths_to_own.append(recordings_path)
    for path in paths_to_own:
        os.chown(path, account.pw_uid, account.pw_gid)


def drop_privileges() -> None:
    """Run the web application as the same unprivileged user as the base image."""

    if os.geteuid() != 0:
        return
    account = pwd.getpwnam(APP_USER)
    os.initgroups(APP_USER, account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.environ["HOME"] = account.pw_dir


def main() -> None:
    options = load_home_assistant_options()
    home_assistant = options is not None
    if options is not None:
        configure_home_assistant(options)

    prepare_runtime_paths(home_assistant)
    drop_privileges()

    port = os.environ.get("TBC_PORT", "8732")
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "tbc.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
        "--app-dir",
        "/app/app",
    ]
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"TBC-Start fehlgeschlagen: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
