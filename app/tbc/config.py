from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "TBC"
    admin_username: str = "admin"
    admin_password: str = "bitte-aendern"
    database_path: str = "/data/tbc.sqlite3"
    recordings_path: str = "/recordings"
    live_path: str = "/tmp/tbc-live"
    dashboard_snapshots_path: str = "/data/dashboard-snapshots"
    dashboard_snapshot_interval_seconds: int = 600
    public_base_url: str = ""
    secret_key: str = "lokaler-dev-schluessel-bitte-aendern"
    poll_interval_seconds: int = 60
    web_port: int = 8732
    cookie_secure: bool = False
    camera_modules_path: str = "/data/camera-modules"
    theme_modules_path: str = "/data/design-themes"


def load_settings() -> Settings:
    return Settings(
        admin_username=os.getenv("TBC_ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("TBC_ADMIN_PASSWORD", "bitte-aendern"),
        database_path=os.getenv("TBC_DATABASE_PATH", "/data/tbc.sqlite3"),
        recordings_path=os.getenv("TBC_RECORDINGS_PATH", "/recordings"),
        live_path=os.getenv("TBC_LIVE_PATH", "/tmp/tbc-live"),
        dashboard_snapshots_path=os.getenv("TBC_DASHBOARD_SNAPSHOTS_PATH", "/data/dashboard-snapshots"),
        dashboard_snapshot_interval_seconds=max(
            60,
            int(os.getenv("TBC_DASHBOARD_SNAPSHOT_INTERVAL_SECONDS", "600")),
        ),
        public_base_url=os.getenv("TBC_PUBLIC_BASE_URL", "").rstrip("/"),
        secret_key=os.getenv("TBC_SECRET_KEY", "lokaler-dev-schluessel-bitte-aendern"),
        poll_interval_seconds=max(15, int(os.getenv("TBC_POLL_INTERVAL_SECONDS", "60"))),
        web_port=int(os.getenv("TBC_PORT", "8732")),
        cookie_secure=os.getenv("TBC_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
        camera_modules_path=os.getenv("TBC_CAMERA_MODULES_PATH", "/data/camera-modules"),
        theme_modules_path=os.getenv("TBC_THEME_MODULES_PATH", "/data/design-themes"),
    )
