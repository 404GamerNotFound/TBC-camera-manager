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
    # 14 days matches Starlette's own SessionMiddleware default - kept as
    # the default here so leaving TBC_SESSION_MAX_AGE_SECONDS unset doesn't
    # change behavior for existing deployments, just makes it configurable.
    session_max_age_seconds: int = 14 * 24 * 60 * 60
    camera_modules_path: str = "/data/camera-modules"
    theme_modules_path: str = "/data/design-themes"
    cloud_modules_path: str = "/data/cloud-modules"
    network_modules_path: str = "/data/network-modules"
    detection_models_path: str = "/data/detection-models"
    detection_default_sample_fps: float = 2.0
    detection_default_confidence_threshold: float = 0.5


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
        session_max_age_seconds=max(300, int(os.getenv("TBC_SESSION_MAX_AGE_SECONDS", str(14 * 24 * 60 * 60)))),
        camera_modules_path=os.getenv("TBC_CAMERA_MODULES_PATH", "/data/camera-modules"),
        theme_modules_path=os.getenv("TBC_THEME_MODULES_PATH", "/data/design-themes"),
        cloud_modules_path=os.getenv("TBC_CLOUD_MODULES_PATH", "/data/cloud-modules"),
        network_modules_path=os.getenv("TBC_NETWORK_MODULES_PATH", "/data/network-modules"),
        detection_models_path=os.getenv("TBC_DETECTION_MODELS_PATH", "/data/detection-models"),
        detection_default_sample_fps=max(0.1, float(os.getenv("TBC_DETECTION_SAMPLE_FPS", "2.0"))),
        detection_default_confidence_threshold=min(
            1.0, max(0.05, float(os.getenv("TBC_DETECTION_CONFIDENCE_THRESHOLD", "0.5")))
        ),
    )
