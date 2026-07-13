from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from .security import hash_password, verify_password


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_key TEXT NOT NULL DEFAULT 'reolink',
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    onvif_port INTEGER NOT NULL DEFAULT 8000,
    http_port INTEGER NOT NULL DEFAULT 80,
    rtsp_port INTEGER NOT NULL DEFAULT 554,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    manufacturer TEXT,
    model TEXT,
    firmware TEXT,
    serial TEXT,
    manual_stream_uri TEXT,
    stream_uri TEXT,
    recording_enabled INTEGER NOT NULL DEFAULT 0,
    recording_duration_seconds INTEGER NOT NULL DEFAULT 30,
    recording_pre_seconds INTEGER NOT NULL DEFAULT 0,
    recording_post_seconds INTEGER NOT NULL DEFAULT 10,
    recording_cooldown_seconds INTEGER NOT NULL DEFAULT 90,
    snapshot_enabled INTEGER NOT NULL DEFAULT 1,
    recording_storage_id INTEGER,
    recording_last_started_at TEXT,
    continuous_recording_enabled INTEGER NOT NULL DEFAULT 0,
    continuous_segment_seconds INTEGER NOT NULL DEFAULT 300,
    continuous_storage_id INTEGER,
    last_probe_at TEXT,
    last_probe_status TEXT,
    last_probe_message TEXT,
    performance_cpu REAL,
    performance_codec_rate INTEGER,
    performance_net_throughput INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_camera_access (
    user_id INTEGER NOT NULL,
    camera_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
    UNIQUE(user_id, camera_id)
);

CREATE TABLE IF NOT EXISTS storage_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'local',
    local_path TEXT,
    s3_endpoint_url TEXT,
    s3_region TEXT,
    s3_bucket TEXT,
    s3_prefix TEXT,
    s3_access_key_id TEXT,
    s3_secret_access_key TEXT,
    retention_days INTEGER,
    retention_max_gb REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS camera_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    channel_index INTEGER NOT NULL,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    stream_uri TEXT,
    last_seen_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
    UNIQUE(camera_id, channel_index)
);

CREATE TABLE IF NOT EXISTS camera_detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    detection_key TEXT NOT NULL,
    label TEXT NOT NULL,
    category TEXT NOT NULL,
    channel INTEGER,
    supported INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'catalog',
    last_seen TEXT,
    raw_value TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
    UNIQUE(camera_id, detection_key)
);

CREATE TABLE IF NOT EXISTS camera_recording_triggers (
    camera_id INTEGER NOT NULL,
    detection_key TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
    UNIQUE(camera_id, detection_key)
);

CREATE TABLE IF NOT EXISTS camera_detection_settings (
    camera_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    backend TEXT NOT NULL DEFAULT 'cpu',
    confidence_threshold REAL NOT NULL DEFAULT 0.5,
    sample_fps REAL NOT NULL DEFAULT 2.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS camera_detection_zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'include',
    classes_json TEXT,
    points_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS camera_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    detection_key TEXT,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    storage_id INTEGER,
    detection_key TEXT NOT NULL,
    event_label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'recording',
    storage_kind TEXT NOT NULL DEFAULT 'local',
    file_name TEXT,
    local_path TEXT,
    remote_key TEXT,
    snapshot_path TEXT,
    snapshot_remote_key TEXT,
    mime_type TEXT NOT NULL DEFAULT 'video/mp4',
    duration_seconds INTEGER,
    size_bytes INTEGER,
    message TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
    FOREIGN KEY(storage_id) REFERENCES storage_targets(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS retention_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    camera_id INTEGER,
    detection_key TEXT,
    max_age_days INTEGER,
    max_size_gb REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notification_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    event_filter TEXT,
    url TEXT,
    token TEXT,
    chat_id TEXT,
    email_to TEXT,
    email_from TEXT,
    smtp_host TEXT,
    smtp_port INTEGER,
    smtp_username TEXT,
    smtp_password TEXT,
    ha_service TEXT,
    include_snapshot INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS health_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_type TEXT NOT NULL,
    component_id TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(component_type, component_id)
);

CREATE TABLE IF NOT EXISTS health_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_type TEXT NOT NULL,
    component_id TEXT NOT NULL,
    previous_status TEXT,
    status TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mqtt_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 0,
    host TEXT,
    port INTEGER NOT NULL DEFAULT 1883,
    username TEXT,
    password TEXT,
    topic_prefix TEXT NOT NULL DEFAULT 'tbc',
    discovery_enabled INTEGER NOT NULL DEFAULT 1,
    discovery_prefix TEXT NOT NULL DEFAULT 'homeassistant',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ui_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active_theme_key TEXT NOT NULL DEFAULT 'standard',
    live_grid_columns INTEGER NOT NULL DEFAULT 3,
    live_rotation_enabled INTEGER NOT NULL DEFAULT 0,
    live_rotation_seconds INTEGER NOT NULL DEFAULT 15,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_layout (
    live_key TEXT PRIMARY KEY,
    column_span INTEGER NOT NULL DEFAULT 1,
    row_span INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cloud_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_key TEXT NOT NULL,
    label TEXT NOT NULL,
    host TEXT,
    port INTEGER,
    verify_ssl INTEGER NOT NULL DEFAULT 0,
    identifier TEXT NOT NULL,
    secret TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_test_status TEXT,
    last_test_message TEXT,
    last_test_at TEXT,
    pending_verification_field TEXT,
    pending_verification_message TEXT,
    pending_verification_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plugin_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_kind TEXT NOT NULL,
    label TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    ref TEXT NOT NULL DEFAULT 'main',
    subdirectory TEXT NOT NULL DEFAULT '',
    installed_key TEXT,
    installed_ref_sha TEXT,
    latest_ref_sha TEXT,
    update_available INTEGER NOT NULL DEFAULT 0,
    last_sync_status TEXT,
    last_sync_message TEXT,
    last_sync_at TEXT,
    last_checked_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE cameras ADD COLUMN module_key TEXT NOT NULL DEFAULT 'reolink'",
    "ALTER TABLE cameras ADD COLUMN rtsp_port INTEGER NOT NULL DEFAULT 554",
    "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'",
    "ALTER TABLE cameras ADD COLUMN recording_enabled INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE cameras ADD COLUMN recording_duration_seconds INTEGER NOT NULL DEFAULT 30",
    "ALTER TABLE cameras ADD COLUMN recording_pre_seconds INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE cameras ADD COLUMN recording_post_seconds INTEGER NOT NULL DEFAULT 10",
    "ALTER TABLE cameras ADD COLUMN recording_cooldown_seconds INTEGER NOT NULL DEFAULT 90",
    "ALTER TABLE cameras ADD COLUMN snapshot_enabled INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE cameras ADD COLUMN recording_storage_id INTEGER",
    "ALTER TABLE cameras ADD COLUMN recording_last_started_at TEXT",
    "ALTER TABLE cameras ADD COLUMN manual_stream_uri TEXT",
    "ALTER TABLE cameras ADD COLUMN performance_cpu REAL",
    "ALTER TABLE cameras ADD COLUMN performance_codec_rate INTEGER",
    "ALTER TABLE cameras ADD COLUMN performance_net_throughput INTEGER",
    "ALTER TABLE storage_targets ADD COLUMN retention_days INTEGER",
    "ALTER TABLE storage_targets ADD COLUMN retention_max_gb REAL",
    "ALTER TABLE cameras ADD COLUMN continuous_recording_enabled INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE cameras ADD COLUMN continuous_segment_seconds INTEGER NOT NULL DEFAULT 300",
    "ALTER TABLE cameras ADD COLUMN continuous_storage_id INTEGER",
    "ALTER TABLE ui_settings ADD COLUMN live_grid_columns INTEGER NOT NULL DEFAULT 3",
    "ALTER TABLE ui_settings ADD COLUMN live_rotation_enabled INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE ui_settings ADD COLUMN live_rotation_seconds INTEGER NOT NULL DEFAULT 15",
    "ALTER TABLE cloud_accounts ADD COLUMN config_json TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE cloud_accounts ADD COLUMN pending_verification_field TEXT",
    "ALTER TABLE cloud_accounts ADD COLUMN pending_verification_message TEXT",
    "ALTER TABLE cloud_accounts ADD COLUMN pending_verification_at TEXT",
    "ALTER TABLE plugin_sources ADD COLUMN installed_ref_sha TEXT",
    "ALTER TABLE plugin_sources ADD COLUMN latest_ref_sha TEXT",
    "ALTER TABLE plugin_sources ADD COLUMN update_available INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE plugin_sources ADD COLUMN last_checked_at TEXT",
)


@contextmanager
def connect(database_path: str):
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize(database_path: str, default_recordings_path: str = "/recordings") -> None:
    with connect(database_path) as db:
        db.executescript(SCHEMA)
        for statement in MIGRATIONS:
            try:
                db.execute(statement)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc):
                    raise
        row = db.execute("SELECT COUNT(*) AS total FROM storage_targets").fetchone()
        if row["total"] == 0:
            db.execute(
                """
                INSERT INTO storage_targets (name, kind, local_path)
                VALUES (?, ?, ?)
                """,
                ("Lokaler Container-Speicher", "local", default_recordings_path),
            )
        db.execute(
            """
            INSERT OR IGNORE INTO mqtt_config (id, enabled, host, port, topic_prefix, discovery_enabled, discovery_prefix)
            VALUES (1, 0, NULL, 1883, 'tbc', 1, 'homeassistant')
            """
        )
        db.execute(
            "INSERT OR IGNORE INTO ui_settings (id, active_theme_key) VALUES (1, 'standard')"
        )


def ensure_admin_user(database_path: str, username: str, password: str) -> None:
    with connect(database_path) as db:
        row = db.execute("SELECT COUNT(*) AS total FROM users").fetchone()
        if row["total"] == 0:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
                (username, hash_password(password)),
            )


def authenticate_user(database_path: str, username: str, password: str) -> dict[str, Any] | None:
    with connect(database_path) as db:
        row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return dict(row)


def get_user(database_path: str, user_id: int) -> dict[str, Any] | None:
    with connect(database_path) as db:
        row = db.execute("SELECT id, username, role, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users(database_path: str) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT u.id, u.username, u.role, u.created_at,
                   COUNT(a.camera_id) AS camera_count
              FROM users u
              LEFT JOIN user_camera_access a ON a.user_id = u.id
             GROUP BY u.id
             ORDER BY u.username COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def create_user(database_path: str, *, username: str, password: str, role: str) -> int:
    with connect(database_path) as db:
        cursor = db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, hash_password(password), _valid_role(role)),
        )
        return int(cursor.lastrowid)


def update_user(database_path: str, user_id: int, *, username: str, role: str, password: str | None = None) -> None:
    with connect(database_path) as db:
        if password:
            db.execute(
                "UPDATE users SET username = ?, role = ?, password_hash = ? WHERE id = ?",
                (username, _valid_role(role), hash_password(password), user_id),
            )
        else:
            db.execute(
                "UPDATE users SET username = ?, role = ? WHERE id = ?",
                (username, _valid_role(role), user_id),
            )


def delete_user(database_path: str, user_id: int) -> None:
    with connect(database_path) as db:
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))


def set_user_camera_access(database_path: str, user_id: int, camera_ids: Iterable[int]) -> None:
    with connect(database_path) as db:
        db.execute("DELETE FROM user_camera_access WHERE user_id = ?", (user_id,))
        for camera_id in camera_ids:
            db.execute(
                "INSERT OR IGNORE INTO user_camera_access (user_id, camera_id) VALUES (?, ?)",
                (user_id, int(camera_id)),
            )


def list_user_camera_ids(database_path: str, user_id: int) -> list[int]:
    with connect(database_path) as db:
        rows = db.execute(
            "SELECT camera_id FROM user_camera_access WHERE user_id = ? ORDER BY camera_id",
            (user_id,),
        ).fetchall()
    return [int(row["camera_id"]) for row in rows]


def user_can_access_camera(database_path: str, user_id: int, role: str, camera_id: int) -> bool:
    if role == "admin":
        return True
    with connect(database_path) as db:
        row = db.execute(
            """
            SELECT 1
              FROM user_camera_access
             WHERE user_id = ? AND camera_id = ?
            """,
            (user_id, camera_id),
        ).fetchone()
    return row is not None


def list_cameras(database_path: str) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT c.*,
                   s.name AS storage_name,
                   s.kind AS storage_kind,
                   COUNT(d.id) AS detection_count,
                   SUM(CASE WHEN d.supported = 1 THEN 1 ELSE 0 END) AS supported_count,
                   SUM(CASE WHEN d.active = 1 THEN 1 ELSE 0 END) AS active_count
            FROM cameras c
            LEFT JOIN storage_targets s ON s.id = c.recording_storage_id
            LEFT JOIN camera_detections d ON d.camera_id = c.id
            GROUP BY c.id
            ORDER BY c.name COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_cameras_for_user(database_path: str, user_id: int, role: str) -> list[dict[str, Any]]:
    if role == "admin":
        return list_cameras(database_path)
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT c.*,
                   s.name AS storage_name,
                   s.kind AS storage_kind,
                   COUNT(d.id) AS detection_count,
                   SUM(CASE WHEN d.supported = 1 THEN 1 ELSE 0 END) AS supported_count,
                   SUM(CASE WHEN d.active = 1 THEN 1 ELSE 0 END) AS active_count
              FROM cameras c
              JOIN user_camera_access a ON a.camera_id = c.id AND a.user_id = ?
              LEFT JOIN storage_targets s ON s.id = c.recording_storage_id
              LEFT JOIN camera_detections d ON d.camera_id = c.id
             GROUP BY c.id
             ORDER BY c.name COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_camera(database_path: str, camera_id: int) -> dict[str, Any] | None:
    with connect(database_path) as db:
        row = db.execute(
            """
            SELECT c.*, s.name AS storage_name, s.kind AS storage_kind
              FROM cameras c
              LEFT JOIN storage_targets s ON s.id = c.recording_storage_id
             WHERE c.id = ?
            """,
            (camera_id,),
        ).fetchone()
    return dict(row) if row else None


def count_cameras_by_module(database_path: str, module_key: str) -> int:
    with connect(database_path) as db:
        row = db.execute(
            "SELECT COUNT(*) AS total FROM cameras WHERE module_key = ?",
            (module_key,),
        ).fetchone()
    return int(row["total"] if row else 0)


def create_cloud_account(
    database_path: str,
    *,
    module_key: str,
    label: str,
    host: str | None = None,
    port: int | None = None,
    verify_ssl: bool = False,
    identifier: str = "",
    secret: str = "",
    config: dict[str, Any] | None = None,
) -> int:
    account_config = dict(config or {})
    if not account_config:
        account_config = {
            "host": host or "",
            "port": port or 443,
            "verify_ssl": verify_ssl,
            "identifier": identifier,
            "secret": secret,
        }
    host = str(account_config.get("host") or host or "").strip() or None
    raw_port = account_config.get("port", port)
    port = int(raw_port) if raw_port not in (None, "") else None
    verify_ssl = bool(account_config.get("verify_ssl", verify_ssl))
    identifier = str(account_config.get("identifier") or identifier or "")
    secret = str(account_config.get("secret") or secret or "")
    with connect(database_path) as db:
        cursor = db.execute(
            """
            INSERT INTO cloud_accounts (
                module_key, label, host, port, verify_ssl, identifier, secret, config_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                module_key,
                label,
                host,
                port,
                1 if verify_ssl else 0,
                identifier,
                secret,
                json.dumps(account_config, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        return int(cursor.lastrowid)


def list_cloud_accounts(database_path: str) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute("SELECT * FROM cloud_accounts ORDER BY label COLLATE NOCASE").fetchall()
    return [_hydrate_cloud_account(row) for row in rows]


def get_cloud_account(database_path: str, account_id: int) -> dict[str, Any] | None:
    with connect(database_path) as db:
        row = db.execute("SELECT * FROM cloud_accounts WHERE id = ?", (account_id,)).fetchone()
    return _hydrate_cloud_account(row) if row else None


def update_cloud_account_configuration(
    database_path: str,
    account_id: int,
    *,
    label: str,
    config: dict[str, Any],
) -> None:
    host = str(config.get("host") or "").strip() or None
    raw_port = config.get("port")
    port = int(raw_port) if raw_port not in (None, "") else None
    verify_ssl = bool(config.get("verify_ssl", False))
    identifier = str(config.get("identifier") or "")
    secret = str(config.get("secret") or "")
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE cloud_accounts
               SET label = ?, host = ?, port = ?, verify_ssl = ?,
                   identifier = ?, secret = ?, config_json = ?,
                   pending_verification_field = NULL,
                   pending_verification_message = NULL,
                   pending_verification_at = NULL,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                label,
                host,
                port,
                1 if verify_ssl else 0,
                identifier,
                secret,
                json.dumps(config, ensure_ascii=False, separators=(",", ":")),
                account_id,
            ),
        )


def set_cloud_account_pending_verification(
    database_path: str, account_id: int, *, field_key: str, message: str
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE cloud_accounts
               SET pending_verification_field = ?,
                   pending_verification_message = ?,
                   pending_verification_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (field_key, message, account_id),
        )


def clear_cloud_account_pending_verification(database_path: str, account_id: int) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE cloud_accounts
               SET pending_verification_field = NULL,
                   pending_verification_message = NULL,
                   pending_verification_at = NULL,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (account_id,),
        )


def clear_cloud_account_configuration_fields(
    database_path: str, account_id: int, field_keys: Iterable[str]
) -> None:
    account = get_cloud_account(database_path, account_id)
    if account is None:
        return
    config = dict(account.get("config") or {})
    for key in field_keys:
        if key in config:
            config[key] = ""
    update_cloud_account_configuration(
        database_path,
        account_id,
        label=str(account["label"]),
        config=config,
    )


def _hydrate_cloud_account(row: sqlite3.Row) -> dict[str, Any]:
    account = dict(row)
    try:
        config = json.loads(account.get("config_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        config = {}
    if not isinstance(config, dict) or not config:
        config = {
            "host": account.get("host") or "",
            "port": account.get("port") or 443,
            "verify_ssl": bool(account.get("verify_ssl")),
            "identifier": account.get("identifier") or "",
            "secret": account.get("secret") or "",
        }
    account["config"] = config
    account.update(config)
    return account


def update_cloud_account_test_result(
    database_path: str, account_id: int, *, status: str, message: str
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE cloud_accounts
               SET last_test_status = ?,
                   last_test_message = ?,
                   last_test_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (status, message, account_id),
        )


def delete_cloud_account(database_path: str, account_id: int) -> None:
    with connect(database_path) as db:
        db.execute("DELETE FROM cloud_accounts WHERE id = ?", (account_id,))


def count_cloud_accounts_by_module(database_path: str, module_key: str) -> int:
    with connect(database_path) as db:
        row = db.execute(
            "SELECT COUNT(*) AS total FROM cloud_accounts WHERE module_key = ?",
            (module_key,),
        ).fetchone()
    return int(row["total"] if row else 0)


def create_plugin_source(
    database_path: str,
    *,
    plugin_kind: str,
    label: str,
    repo_url: str,
    ref: str,
    subdirectory: str,
) -> int:
    with connect(database_path) as db:
        cursor = db.execute(
            """
            INSERT INTO plugin_sources (plugin_kind, label, repo_url, ref, subdirectory)
            VALUES (?, ?, ?, ?, ?)
            """,
            (plugin_kind, label, repo_url, ref or "main", subdirectory or ""),
        )
        return int(cursor.lastrowid)


def list_plugin_sources(database_path: str) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute("SELECT * FROM plugin_sources ORDER BY label COLLATE NOCASE").fetchall()
    return [dict(row) for row in rows]


def get_plugin_source(database_path: str, source_id: int) -> dict[str, Any] | None:
    with connect(database_path) as db:
        row = db.execute("SELECT * FROM plugin_sources WHERE id = ?", (source_id,)).fetchone()
    return dict(row) if row else None


def update_plugin_source_sync_result(
    database_path: str,
    source_id: int,
    *,
    status: str,
    message: str,
    installed_key: str | None = None,
    installed_ref_sha: str | None = None,
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE plugin_sources
               SET last_sync_status = ?,
                   last_sync_message = ?,
                   last_sync_at = CURRENT_TIMESTAMP,
                   installed_key = COALESCE(?, installed_key),
                   installed_ref_sha = COALESCE(?, installed_ref_sha),
                   update_available = CASE WHEN ? = 'ok' THEN 0 ELSE update_available END,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (status, message, installed_key, installed_ref_sha, status, source_id),
        )


def update_plugin_source_check_result(
    database_path: str,
    source_id: int,
    *,
    latest_ref_sha: str | None,
    update_available: bool,
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE plugin_sources
               SET latest_ref_sha = ?,
                   update_available = ?,
                   last_checked_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (latest_ref_sha, 1 if update_available else 0, source_id),
        )


def count_plugin_sources_with_update(database_path: str) -> int:
    with connect(database_path) as db:
        row = db.execute(
            "SELECT COUNT(*) AS total FROM plugin_sources WHERE update_available = 1"
        ).fetchone()
    return int(row["total"] if row else 0)


def delete_plugin_source(database_path: str, source_id: int) -> None:
    with connect(database_path) as db:
        db.execute("DELETE FROM plugin_sources WHERE id = ?", (source_id,))


def get_storage_target(database_path: str, storage_id: int) -> dict[str, Any] | None:
    with connect(database_path) as db:
        row = db.execute("SELECT * FROM storage_targets WHERE id = ?", (storage_id,)).fetchone()
    return dict(row) if row else None


def list_storage_targets(database_path: str) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            "SELECT * FROM storage_targets ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


def create_storage_target(
    database_path: str,
    *,
    name: str,
    kind: str,
    local_path: str | None = None,
    s3_endpoint_url: str | None = None,
    s3_region: str | None = None,
    s3_bucket: str | None = None,
    s3_prefix: str | None = None,
    s3_access_key_id: str | None = None,
    s3_secret_access_key: str | None = None,
) -> int:
    with connect(database_path) as db:
        cursor = db.execute(
            """
            INSERT INTO storage_targets (
                name, kind, local_path, s3_endpoint_url, s3_region, s3_bucket,
                s3_prefix, s3_access_key_id, s3_secret_access_key
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                kind,
                local_path,
                s3_endpoint_url,
                s3_region,
                s3_bucket,
                s3_prefix,
                s3_access_key_id,
                s3_secret_access_key,
            ),
        )
        return int(cursor.lastrowid)


def update_storage_target(
    database_path: str,
    storage_id: int,
    *,
    name: str,
    kind: str,
    local_path: str | None = None,
    s3_endpoint_url: str | None = None,
    s3_region: str | None = None,
    s3_bucket: str | None = None,
    s3_prefix: str | None = None,
    s3_access_key_id: str | None = None,
    s3_secret_access_key: str | None = None,
    retention_days: int | None = None,
    retention_max_gb: float | None = None,
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE storage_targets
               SET name = ?,
                   kind = ?,
                   local_path = ?,
                   s3_endpoint_url = ?,
                   s3_region = ?,
                   s3_bucket = ?,
                   s3_prefix = ?,
                   s3_access_key_id = ?,
                   s3_secret_access_key = ?,
                   retention_days = ?,
                   retention_max_gb = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                name,
                kind,
                local_path,
                s3_endpoint_url,
                s3_region,
                s3_bucket,
                s3_prefix,
                s3_access_key_id,
                s3_secret_access_key,
                retention_days,
                retention_max_gb,
                storage_id,
            ),
        )


def delete_storage_target(database_path: str, storage_id: int) -> None:
    with connect(database_path) as db:
        db.execute(
            "UPDATE cameras SET recording_storage_id = NULL WHERE recording_storage_id = ?",
            (storage_id,),
        )
        db.execute("DELETE FROM storage_targets WHERE id = ?", (storage_id,))


def create_camera(
    database_path: str,
    *,
    name: str,
    host: str,
    onvif_port: int,
    http_port: int,
    username: str,
    password: str,
    module_key: str = "reolink",
    rtsp_port: int = 554,
    manual_stream_uri: str | None = None,
) -> int:
    with connect(database_path) as db:
        cursor = db.execute(
            """
            INSERT INTO cameras (
                module_key, name, host, onvif_port, http_port, rtsp_port,
                username, password, manual_stream_uri
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                module_key, name, host, onvif_port, http_port, rtsp_port,
                username, password, manual_stream_uri,
            ),
        )
        return int(cursor.lastrowid)


def delete_camera(database_path: str, camera_id: int) -> None:
    with connect(database_path) as db:
        db.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))


def update_camera_connection(
    database_path: str,
    camera_id: int,
    *,
    name: str,
    host: str,
    onvif_port: int,
    http_port: int,
    username: str,
    password: str | None = None,
    rtsp_port: int | None = None,
    manual_stream_uri: str | None = None,
    clear_manual_stream_uri: bool = False,
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE cameras
               SET name = ?,
                   host = ?,
                   onvif_port = ?,
                   http_port = ?,
                   rtsp_port = COALESCE(?, rtsp_port),
                   username = ?,
                   password = COALESCE(?, password),
                   manual_stream_uri = CASE
                       WHEN ? = 1 THEN NULL
                       WHEN ? IS NOT NULL THEN ?
                       ELSE manual_stream_uri
                   END,
                   manufacturer = NULL,
                   model = NULL,
                   firmware = NULL,
                   serial = NULL,
                   stream_uri = NULL,
                   last_probe_status = NULL,
                   last_probe_message = NULL,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                name, host, onvif_port, http_port, rtsp_port, username, password,
                1 if clear_manual_stream_uri else 0,
                manual_stream_uri,
                manual_stream_uri,
                camera_id,
            ),
        )


def upsert_camera_channels(database_path: str, camera_id: int, channels: Iterable[dict[str, Any]]) -> None:
    with connect(database_path) as db:
        for channel in channels:
            channel_index = int(channel["channel_index"])
            name = str(channel.get("name") or f"Kanal {channel_index + 1}")
            stream_uri = channel.get("stream_uri")
            db.execute(
                """
                INSERT INTO camera_channels (camera_id, channel_index, name, stream_uri, last_seen_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(camera_id, channel_index) DO UPDATE SET
                    name = COALESCE(camera_channels.name, excluded.name),
                    stream_uri = COALESCE(excluded.stream_uri, camera_channels.stream_uri),
                    last_seen_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (camera_id, channel_index, name, stream_uri),
            )


def list_camera_channels(database_path: str, camera_id: int) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT *
              FROM camera_channels
             WHERE camera_id = ?
             ORDER BY channel_index
            """,
            (camera_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_camera_channel(database_path: str, channel_id: int) -> dict[str, Any] | None:
    with connect(database_path) as db:
        row = db.execute(
            """
            SELECT ch.*, c.name AS camera_name, c.stream_uri AS camera_stream_uri
              FROM camera_channels ch
              JOIN cameras c ON c.id = ch.camera_id
             WHERE ch.id = ?
            """,
            (channel_id,),
        ).fetchone()
    return dict(row) if row else None


def update_camera_channel(database_path: str, channel_id: int, *, name: str, enabled: bool) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE camera_channels
               SET name = ?, enabled = ?, updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (name, 1 if enabled else 0, channel_id),
        )


def update_camera_recording_settings(
    database_path: str,
    camera_id: int,
    *,
    recording_enabled: bool,
    recording_duration_seconds: int,
    recording_pre_seconds: int,
    recording_post_seconds: int,
    recording_cooldown_seconds: int,
    snapshot_enabled: bool,
    recording_storage_id: int | None,
    trigger_keys: Iterable[str],
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE cameras
               SET recording_enabled = ?,
                   recording_duration_seconds = ?,
                   recording_pre_seconds = ?,
                   recording_post_seconds = ?,
                   recording_cooldown_seconds = ?,
                   snapshot_enabled = ?,
                   recording_storage_id = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                1 if recording_enabled else 0,
                recording_duration_seconds,
                recording_pre_seconds,
                recording_post_seconds,
                recording_cooldown_seconds,
                1 if snapshot_enabled else 0,
                recording_storage_id,
                camera_id,
            ),
        )
        db.execute("DELETE FROM camera_recording_triggers WHERE camera_id = ?", (camera_id,))
        for trigger_key in trigger_keys:
            db.execute(
                """
                INSERT INTO camera_recording_triggers (camera_id, detection_key, enabled)
                VALUES (?, ?, 1)
                """,
                (camera_id, trigger_key),
            )


def update_camera_continuous_settings(
    database_path: str,
    camera_id: int,
    *,
    continuous_recording_enabled: bool,
    continuous_segment_seconds: int,
    continuous_storage_id: int | None,
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE cameras
               SET continuous_recording_enabled = ?,
                   continuous_segment_seconds = ?,
                   continuous_storage_id = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                1 if continuous_recording_enabled else 0,
                continuous_segment_seconds,
                continuous_storage_id,
                camera_id,
            ),
        )


def list_camera_recording_triggers(database_path: str, camera_id: int) -> list[str]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT detection_key
              FROM camera_recording_triggers
             WHERE camera_id = ? AND enabled = 1
             ORDER BY detection_key
            """,
            (camera_id,),
        ).fetchall()
    return [str(row["detection_key"]) for row in rows]


def get_camera_detection_settings(database_path: str, camera_id: int) -> dict[str, Any] | None:
    with connect(database_path) as db:
        row = db.execute(
            "SELECT * FROM camera_detection_settings WHERE camera_id = ?",
            (camera_id,),
        ).fetchone()
    if row is None:
        return None
    settings = dict(row)
    settings["enabled"] = bool(settings["enabled"])
    return settings


def update_camera_detection_settings(
    database_path: str,
    camera_id: int,
    *,
    enabled: bool,
    backend: str,
    confidence_threshold: float,
    sample_fps: float,
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            INSERT INTO camera_detection_settings (camera_id, enabled, backend, confidence_threshold, sample_fps, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(camera_id) DO UPDATE SET
                enabled = excluded.enabled,
                backend = excluded.backend,
                confidence_threshold = excluded.confidence_threshold,
                sample_fps = excluded.sample_fps,
                updated_at = CURRENT_TIMESTAMP
            """,
            (camera_id, 1 if enabled else 0, backend, confidence_threshold, sample_fps),
        )


def list_enabled_camera_detection_settings(database_path: str) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT c.id AS camera_id,
                   c.name AS camera_name,
                   s.backend,
                   s.confidence_threshold,
                   s.sample_fps,
                   (SELECT COUNT(*) FROM camera_detection_zones z WHERE z.camera_id = c.id) AS zone_count
              FROM camera_detection_settings s
              JOIN cameras c ON c.id = s.camera_id
             WHERE s.enabled = 1
             ORDER BY c.name COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_camera_detection_zones(database_path: str, camera_id: int) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            "SELECT * FROM camera_detection_zones WHERE camera_id = ? ORDER BY id",
            (camera_id,),
        ).fetchall()
    return [_detection_zone_row(row) for row in rows]


def get_camera_detection_zone(database_path: str, zone_id: int) -> dict[str, Any] | None:
    with connect(database_path) as db:
        row = db.execute("SELECT * FROM camera_detection_zones WHERE id = ?", (zone_id,)).fetchone()
    return _detection_zone_row(row) if row is not None else None


def create_camera_detection_zone(
    database_path: str,
    camera_id: int,
    *,
    name: str,
    mode: str,
    classes: list[str] | None,
    points: list[tuple[float, float]],
) -> int:
    with connect(database_path) as db:
        cursor = db.execute(
            """
            INSERT INTO camera_detection_zones (camera_id, name, mode, classes_json, points_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                name,
                _valid_zone_mode(mode),
                json.dumps(list(classes)) if classes else None,
                json.dumps([list(point) for point in points]),
            ),
        )
        return int(cursor.lastrowid)


def delete_camera_detection_zone(database_path: str, camera_id: int, zone_id: int) -> None:
    with connect(database_path) as db:
        db.execute(
            "DELETE FROM camera_detection_zones WHERE id = ? AND camera_id = ?",
            (zone_id, camera_id),
        )


def _detection_zone_row(row: sqlite3.Row) -> dict[str, Any]:
    zone = dict(row)
    zone["classes"] = json.loads(zone["classes_json"]) if zone["classes_json"] else None
    zone["points"] = json.loads(zone["points_json"])
    return zone


def _valid_zone_mode(mode: str) -> str:
    return "exclude" if mode == "exclude" else "include"


def mark_recording_started(database_path: str, camera_id: int) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE cameras
               SET recording_last_started_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (camera_id,),
        )


def list_recent_events(database_path: str, camera_id: int, limit: int = 20) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT *
              FROM camera_events
             WHERE camera_id = ?
             ORDER BY id DESC
             LIMIT ?
            """,
            (camera_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def create_recording(
    database_path: str,
    *,
    camera_id: int,
    storage_id: int | None,
    detection_key: str,
    event_label: str,
    storage_kind: str,
    started_at: str,
) -> int:
    with connect(database_path) as db:
        cursor = db.execute(
            """
            INSERT INTO recordings (
                camera_id, storage_id, detection_key, event_label, storage_kind, status, started_at
            )
            VALUES (?, ?, ?, ?, ?, 'recording', ?)
            """,
            (camera_id, storage_id, detection_key, event_label, storage_kind, started_at),
        )
        return int(cursor.lastrowid)


def update_recording_finished(
    database_path: str,
    recording_id: int,
    *,
    status: str,
    file_name: str | None = None,
    local_path: str | None = None,
    remote_key: str | None = None,
    snapshot_path: str | None = None,
    snapshot_remote_key: str | None = None,
    duration_seconds: int | None = None,
    size_bytes: int | None = None,
    message: str | None = None,
    ended_at: str | None = None,
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE recordings
               SET status = ?,
                   file_name = COALESCE(?, file_name),
                   local_path = COALESCE(?, local_path),
                   remote_key = COALESCE(?, remote_key),
                   snapshot_path = COALESCE(?, snapshot_path),
                   snapshot_remote_key = COALESCE(?, snapshot_remote_key),
                   duration_seconds = COALESCE(?, duration_seconds),
                   size_bytes = COALESCE(?, size_bytes),
                   message = ?,
                   ended_at = COALESCE(?, ended_at),
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                status,
                file_name,
                local_path,
                remote_key,
                snapshot_path,
                snapshot_remote_key,
                duration_seconds,
                size_bytes,
                message,
                ended_at,
                recording_id,
            ),
        )


def create_continuous_recording(
    database_path: str,
    *,
    camera_id: int,
    storage_id: int,
    storage_kind: str,
    file_name: str,
    local_path: str | None,
    remote_key: str | None,
    duration_seconds: int,
    size_bytes: int,
    started_at: str,
    ended_at: str,
) -> int:
    with connect(database_path) as db:
        cursor = db.execute(
            """
            INSERT INTO recordings (
                camera_id, storage_id, detection_key, event_label, status, storage_kind,
                file_name, local_path, remote_key, duration_seconds, size_bytes,
                started_at, ended_at
            )
            VALUES (?, ?, 'continuous', 'Daueraufzeichnung', 'ready', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                storage_id,
                storage_kind,
                file_name,
                local_path,
                remote_key,
                duration_seconds,
                size_bytes,
                started_at,
                ended_at,
            ),
        )
        return int(cursor.lastrowid)


def list_continuous_file_names(database_path: str, camera_id: int, limit: int = 3000) -> list[str]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT file_name
              FROM recordings
             WHERE camera_id = ? AND detection_key = 'continuous' AND file_name IS NOT NULL
             ORDER BY id DESC
             LIMIT ?
            """,
            (camera_id, limit),
        ).fetchall()
    return [str(row["file_name"]) for row in rows]


def list_recordings_for_range(
    database_path: str,
    *,
    camera_id: int,
    start_at: str,
    end_at: str,
) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT r.*, c.name AS camera_name
              FROM recordings r
              JOIN cameras c ON c.id = r.camera_id
             WHERE r.camera_id = ? AND r.status = 'ready'
               AND r.started_at >= ? AND r.started_at < ?
             ORDER BY r.started_at ASC, r.id ASC
            """,
            (camera_id, start_at, end_at),
        ).fetchall()
    return [dict(row) for row in rows]


def get_recording(database_path: str, recording_id: int) -> dict[str, Any] | None:
    with connect(database_path) as db:
        row = db.execute(
            """
            SELECT r.*, c.name AS camera_name, s.kind AS target_kind,
                   s.s3_endpoint_url, s.s3_region, s.s3_bucket, s.s3_prefix,
                   s.s3_access_key_id, s.s3_secret_access_key
              FROM recordings r
              JOIN cameras c ON c.id = r.camera_id
              LEFT JOIN storage_targets s ON s.id = r.storage_id
             WHERE r.id = ?
            """,
            (recording_id,),
        ).fetchone()
    return dict(row) if row else None


def list_recordings(
    database_path: str,
    *,
    camera_id: int | None = None,
    detection_key: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user_id: int | None = None,
    role: str = "admin",
    limit: int = 200,
) -> list[dict[str, Any]]:
    filters = []
    params: list[Any] = []
    if camera_id:
        filters.append("r.camera_id = ?")
        params.append(camera_id)
    if detection_key:
        filters.append("r.detection_key = ?")
        params.append(detection_key)
    else:
        filters.append("r.detection_key != 'continuous'")
    if date_from:
        filters.append("r.started_at >= ?")
        params.append(date_from)
    if date_to:
        filters.append("r.started_at <= ?")
        params.append(date_to)
    join_access = ""
    if role != "admin":
        join_access = "JOIN user_camera_access a ON a.camera_id = r.camera_id AND a.user_id = ?"
        params.insert(0, user_id)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    sql = f"""
        SELECT r.*, c.name AS camera_name
          FROM recordings r
          JOIN cameras c ON c.id = r.camera_id
          {join_access}
          {where}
         ORDER BY r.started_at DESC, r.id DESC
         LIMIT ?
    """
    params.append(limit)
    with connect(database_path) as db:
        rows = db.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def delete_recording_metadata(database_path: str, recording_id: int) -> None:
    with connect(database_path) as db:
        db.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))


def list_recording_event_keys(database_path: str) -> list[str]:
    with connect(database_path) as db:
        rows = db.execute(
            "SELECT DISTINCT detection_key FROM recordings ORDER BY detection_key"
        ).fetchall()
    return [str(row["detection_key"]) for row in rows]


def list_recording_sizes_by_camera_event(database_path: str) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT c.name AS camera_name, r.camera_id, r.detection_key,
                   COUNT(*) AS clip_count,
                   COALESCE(SUM(r.size_bytes), 0) AS size_bytes
              FROM recordings r
              JOIN cameras c ON c.id = r.camera_id
             WHERE r.status = 'ready'
             GROUP BY r.camera_id, r.detection_key
             ORDER BY size_bytes DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_ready_recordings_for_cleanup(database_path: str) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT r.*, c.name AS camera_name
              FROM recordings r
              JOIN cameras c ON c.id = r.camera_id
             WHERE r.status = 'ready'
             ORDER BY r.started_at ASC, r.id ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_retention_rules(database_path: str) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT rr.*, c.name AS camera_name
              FROM retention_rules rr
              LEFT JOIN cameras c ON c.id = rr.camera_id
             ORDER BY rr.enabled DESC, rr.name COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def create_retention_rule(
    database_path: str,
    *,
    name: str,
    enabled: bool,
    camera_id: int | None,
    detection_key: str | None,
    max_age_days: int | None,
    max_size_gb: float | None,
) -> int:
    with connect(database_path) as db:
        cursor = db.execute(
            """
            INSERT INTO retention_rules (
                name, enabled, camera_id, detection_key, max_age_days, max_size_gb
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, 1 if enabled else 0, camera_id, detection_key, max_age_days, max_size_gb),
        )
        return int(cursor.lastrowid)


def update_retention_rule(
    database_path: str,
    rule_id: int,
    *,
    name: str,
    enabled: bool,
    camera_id: int | None,
    detection_key: str | None,
    max_age_days: int | None,
    max_size_gb: float | None,
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE retention_rules
               SET name = ?,
                   enabled = ?,
                   camera_id = ?,
                   detection_key = ?,
                   max_age_days = ?,
                   max_size_gb = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (name, 1 if enabled else 0, camera_id, detection_key, max_age_days, max_size_gb, rule_id),
        )


def delete_retention_rule(database_path: str, rule_id: int) -> None:
    with connect(database_path) as db:
        db.execute("DELETE FROM retention_rules WHERE id = ?", (rule_id,))


def list_notification_channels(database_path: str) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            "SELECT * FROM notification_channels ORDER BY enabled DESC, name COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


def create_notification_channel(database_path: str, **values: Any) -> int:
    with connect(database_path) as db:
        cursor = db.execute(
            """
            INSERT INTO notification_channels (
                name, kind, enabled, event_filter, url, token, chat_id, email_to, email_from,
                smtp_host, smtp_port, smtp_username, smtp_password, ha_service, include_snapshot
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _notification_values(values),
        )
        return int(cursor.lastrowid)


def update_notification_channel(database_path: str, channel_id: int, **values: Any) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE notification_channels
               SET name = ?,
                   kind = ?,
                   enabled = ?,
                   event_filter = ?,
                   url = ?,
                   token = ?,
                   chat_id = ?,
                   email_to = ?,
                   email_from = ?,
                   smtp_host = ?,
                   smtp_port = ?,
                   smtp_username = ?,
                   smtp_password = ?,
                   ha_service = ?,
                   include_snapshot = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (*_notification_values(values), channel_id),
        )


def delete_notification_channel(database_path: str, channel_id: int) -> None:
    with connect(database_path) as db:
        db.execute("DELETE FROM notification_channels WHERE id = ?", (channel_id,))


def upsert_health_status(
    database_path: str,
    *,
    component_type: str,
    component_id: str,
    status: str,
    message: str | None = None,
) -> None:
    with connect(database_path) as db:
        previous = db.execute(
            """
            SELECT status
              FROM health_status
             WHERE component_type = ? AND component_id = ?
            """,
            (component_type, component_id),
        ).fetchone()
        db.execute(
            """
            INSERT INTO health_status (component_type, component_id, status, message, checked_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(component_type, component_id) DO UPDATE SET
                status = excluded.status,
                message = excluded.message,
                checked_at = CURRENT_TIMESTAMP
            """,
            (component_type, component_id, status, message),
        )
        if previous is None or previous["status"] != status:
            db.execute(
                """
                INSERT INTO health_events (
                    component_type, component_id, previous_status, status, message
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (component_type, component_id, previous["status"] if previous else None, status, message),
            )


def list_health_status(database_path: str) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT *
              FROM health_status
             ORDER BY CASE status WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                      component_type, component_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_health_events(database_path: str, limit: int = 100) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT *
              FROM health_events
             ORDER BY id DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_camera_probe(
    database_path: str,
    camera_id: int,
    *,
    status: str,
    message: str,
    manufacturer: str | None = None,
    model: str | None = None,
    firmware: str | None = None,
    serial: str | None = None,
    stream_uri: str | None = None,
    metrics: dict[str, int | float] | None = None,
) -> None:
    metrics = metrics or {}
    with connect(database_path) as db:
        db.execute(
            """
            UPDATE cameras
               SET manufacturer = COALESCE(?, manufacturer),
                   model = COALESCE(?, model),
                   firmware = COALESCE(?, firmware),
                   serial = COALESCE(?, serial),
                   stream_uri = COALESCE(?, stream_uri),
                   performance_cpu = ?,
                   performance_codec_rate = ?,
                   performance_net_throughput = ?,
                   last_probe_at = CURRENT_TIMESTAMP,
                   last_probe_status = ?,
                   last_probe_message = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                manufacturer,
                model,
                firmware,
                serial,
                stream_uri,
                metrics.get("cpu_used"),
                metrics.get("codec_rate"),
                metrics.get("net_throughput"),
                status,
                message,
                camera_id,
            ),
        )


def replace_detections(database_path: str, camera_id: int, detections: Iterable[dict[str, Any]]) -> None:
    with connect(database_path) as db:
        for detection in detections:
            db.execute(
                """
                INSERT INTO camera_detections (
                    camera_id, detection_key, label, category, channel, supported, active,
                    source, last_seen, raw_value, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(camera_id, detection_key) DO UPDATE SET
                    label = excluded.label,
                    category = excluded.category,
                    channel = excluded.channel,
                    supported = excluded.supported,
                    active = excluded.active,
                    source = excluded.source,
                    last_seen = COALESCE(excluded.last_seen, camera_detections.last_seen),
                    raw_value = excluded.raw_value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    camera_id,
                    detection["key"],
                    detection["label"],
                    detection["category"],
                    detection.get("channel"),
                    1 if detection.get("supported") else 0,
                    1 if detection.get("active") else 0,
                    detection.get("source", "catalog"),
                    detection.get("last_seen"),
                    detection.get("raw_value"),
                ),
            )


def list_detections(database_path: str, camera_id: int) -> list[dict[str, Any]]:
    with connect(database_path) as db:
        rows = db.execute(
            """
            SELECT *
              FROM camera_detections
             WHERE camera_id = ?
             ORDER BY channel IS NULL, channel, category, label COLLATE NOCASE
            """,
            (camera_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def record_event(
    database_path: str,
    camera_id: int,
    *,
    event_type: str,
    source: str,
    detection_key: str | None = None,
    payload: str | None = None,
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            INSERT INTO camera_events (camera_id, detection_key, event_type, source, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (camera_id, detection_key, event_type, source, payload),
        )


def get_mqtt_config(database_path: str) -> dict[str, Any]:
    with connect(database_path) as db:
        row = db.execute("SELECT * FROM mqtt_config WHERE id = 1").fetchone()
        if row is None:
            db.execute(
                """
                INSERT INTO mqtt_config (id, enabled, host, port, topic_prefix, discovery_enabled, discovery_prefix)
                VALUES (1, 0, NULL, 1883, 'tbc', 1, 'homeassistant')
                """
            )
            row = db.execute("SELECT * FROM mqtt_config WHERE id = 1").fetchone()
    return dict(row)


def update_mqtt_config(
    database_path: str,
    *,
    enabled: bool,
    host: str | None,
    port: int,
    username: str | None,
    password: str | None,
    topic_prefix: str,
    discovery_enabled: bool,
    discovery_prefix: str,
) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            INSERT INTO mqtt_config (
                id, enabled, host, port, username, password, topic_prefix, discovery_enabled, discovery_prefix
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                enabled = excluded.enabled,
                host = excluded.host,
                port = excluded.port,
                username = excluded.username,
                password = excluded.password,
                topic_prefix = excluded.topic_prefix,
                discovery_enabled = excluded.discovery_enabled,
                discovery_prefix = excluded.discovery_prefix,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                1 if enabled else 0,
                host,
                port,
                username,
                password,
                topic_prefix,
                1 if discovery_enabled else 0,
                discovery_prefix,
            ),
        )


def get_active_theme_key(database_path: str) -> str:
    with connect(database_path) as db:
        row = db.execute("SELECT active_theme_key FROM ui_settings WHERE id = 1").fetchone()
        if row is None:
            db.execute("INSERT OR IGNORE INTO ui_settings (id, active_theme_key) VALUES (1, 'standard')")
            return "standard"
    return str(row["active_theme_key"])


def set_active_theme_key(database_path: str, theme_key: str) -> None:
    with connect(database_path) as db:
        db.execute(
            """
            INSERT INTO ui_settings (id, active_theme_key)
            VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET
                active_theme_key = excluded.active_theme_key,
                updated_at = CURRENT_TIMESTAMP
            """,
            (theme_key,),
        )


def get_live_wall_settings(database_path: str) -> dict[str, Any]:
    with connect(database_path) as db:
        row = db.execute(
            "SELECT live_grid_columns, live_rotation_enabled, live_rotation_seconds FROM ui_settings WHERE id = 1"
        ).fetchone()
        if row is None:
            db.execute("INSERT OR IGNORE INTO ui_settings (id) VALUES (1)")
            return {"columns": 3, "rotation_enabled": False, "rotation_seconds": 15}
    return {
        "columns": int(row["live_grid_columns"]),
        "rotation_enabled": bool(row["live_rotation_enabled"]),
        "rotation_seconds": int(row["live_rotation_seconds"]),
    }


def set_live_wall_settings(
    database_path: str, *, columns: int, rotation_enabled: bool, rotation_seconds: int
) -> None:
    columns = max(1, min(6, columns))
    rotation_seconds = max(5, min(300, rotation_seconds))
    with connect(database_path) as db:
        db.execute(
            """
            INSERT INTO ui_settings (id, live_grid_columns, live_rotation_enabled, live_rotation_seconds)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                live_grid_columns = excluded.live_grid_columns,
                live_rotation_enabled = excluded.live_rotation_enabled,
                live_rotation_seconds = excluded.live_rotation_seconds,
                updated_at = CURRENT_TIMESTAMP
            """,
            (columns, 1 if rotation_enabled else 0, rotation_seconds),
        )


def get_live_layout(database_path: str) -> dict[str, dict[str, int]]:
    with connect(database_path) as db:
        rows = db.execute("SELECT live_key, column_span, row_span, sort_order FROM live_layout").fetchall()
    return {
        str(row["live_key"]): {
            "column_span": int(row["column_span"]),
            "row_span": int(row["row_span"]),
            "sort_order": int(row["sort_order"]),
        }
        for row in rows
    }


def set_live_layout_item(
    database_path: str, live_key: str, *, column_span: int, row_span: int, sort_order: int
) -> None:
    column_span = max(1, min(4, column_span))
    row_span = max(1, min(4, row_span))
    with connect(database_path) as db:
        db.execute(
            """
            INSERT INTO live_layout (live_key, column_span, row_span, sort_order)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(live_key) DO UPDATE SET
                column_span = excluded.column_span,
                row_span = excluded.row_span,
                sort_order = excluded.sort_order,
                updated_at = CURRENT_TIMESTAMP
            """,
            (live_key, column_span, row_span, sort_order),
        )


def _valid_role(role: str) -> str:
    return "viewer" if role == "viewer" else "admin"


def _notification_values(values: dict[str, Any]) -> tuple[Any, ...]:
    return (
        values.get("name"),
        values.get("kind"),
        1 if values.get("enabled") else 0,
        values.get("event_filter"),
        values.get("url"),
        values.get("token"),
        values.get("chat_id"),
        values.get("email_to"),
        values.get("email_from"),
        values.get("smtp_host"),
        values.get("smtp_port"),
        values.get("smtp_username"),
        values.get("smtp_password"),
        values.get("ha_service"),
        1 if values.get("include_snapshot") else 0,
    )
