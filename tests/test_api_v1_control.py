"""Tests for the API-token "control" scope and the new write/stream routes.

These exercise the full FastAPI app via TestClient (unlike the rest of the
suite, which tests app.tbc.database/api_common directly) because the guard
functions and route handlers under test live in app.tbc.main itself. main.py
reads its configuration from TBC_* env vars at import time and creates
directories under those paths, so they must be set to a writable temp
directory *before* main.py is imported - this file is deliberately the only
one in the suite that imports app.tbc.main, to avoid import-order coupling
with any other test module.

The TestClient/app lifespan is started once for the whole module (see
setUpModule/tearDownModule) rather than per test, because app.tbc.main's MCP
session manager is entered via a module-level async context manager that
cannot be safely re-entered after being torn down.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import unittest

_TMP_ROOT = tempfile.mkdtemp(prefix="tbc-api-control-test-")
os.environ.setdefault("TBC_DATABASE_PATH", os.path.join(_TMP_ROOT, "tbc.sqlite3"))
os.environ.setdefault("TBC_DASHBOARD_SNAPSHOTS_PATH", os.path.join(_TMP_ROOT, "dashboard-snapshots"))
os.environ.setdefault("TBC_CAMERA_MODULES_PATH", os.path.join(_TMP_ROOT, "camera-modules"))
os.environ.setdefault("TBC_THEME_MODULES_PATH", os.path.join(_TMP_ROOT, "design-themes"))
os.environ.setdefault("TBC_CLOUD_MODULES_PATH", os.path.join(_TMP_ROOT, "cloud-modules"))
os.environ.setdefault("TBC_DETECTION_MODELS_PATH", os.path.join(_TMP_ROOT, "detection-models"))
os.environ.setdefault("TBC_RECORDINGS_PATH", os.path.join(_TMP_ROOT, "recordings"))
os.environ.setdefault("TBC_LIVE_PATH", os.path.join(_TMP_ROOT, "live"))
os.environ.setdefault("TBC_ADMIN_USERNAME", "admin")
os.environ.setdefault("TBC_ADMIN_PASSWORD", "adminpass123")

from fastapi.testclient import TestClient  # noqa: E402

from app.tbc import database, main  # noqa: E402

TOKEN_PATTERN = re.compile(r"tbc_[A-Za-z0-9_-]{20,}")

_client_cm = None
CLIENT: TestClient


def setUpModule():
    global _client_cm, CLIENT
    _client_cm = TestClient(main.app)
    CLIENT = _client_cm.__enter__()


def tearDownModule():
    _client_cm.__exit__(None, None, None)
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


def _reset_database() -> None:
    db_path = main.SETTINGS.database_path
    if os.path.exists(db_path):
        os.remove(db_path)
    database.initialize(db_path, main.SETTINGS.recordings_path)
    database.ensure_admin_user(db_path, main.SETTINGS.admin_username, main.SETTINGS.admin_password)


def _login() -> None:
    CLIENT.post("/login", data={"username": "admin", "password": "adminpass123"})
    CLIENT.post("/settings/api", data={"enabled": "on", "require_api_key": "on"})


def _create_token(name: str, *, can_control: bool) -> str:
    data = {"name": name}
    if can_control:
        data["can_control"] = "on"
    response = CLIENT.post("/settings/api-tokens", data=data)
    return TOKEN_PATTERN.search(response.text).group(0)


def _create_camera() -> int:
    return database.create_camera(
        main.SETTINGS.database_path,
        name="Front",
        host="203.0.113.5",
        onvif_port=8000,
        http_port=80,
        username="admin",
        password="secret",
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class ApiControlScopeTests(unittest.TestCase):
    def setUp(self):
        _reset_database()
        _login()
        self.camera_id = _create_camera()
        self.read_only_token = _create_token("read-only", can_control=False)
        self.control_token = _create_token("control", can_control=True)

    def test_status_reports_control_scope_per_token(self):
        read_only = CLIENT.get("/api/v1/status", headers=_auth(self.read_only_token))
        control = CLIENT.get("/api/v1/status", headers=_auth(self.control_token))
        self.assertFalse(read_only.json()["api_can_control"])
        self.assertTrue(control.json()["api_can_control"])

    def test_read_only_token_cannot_write_recording_settings(self):
        response = CLIENT.post(
            f"/api/v1/cameras/{self.camera_id}/recording",
            headers=_auth(self.read_only_token),
            json={"enabled": True},
        )
        self.assertEqual(response.status_code, 403)

    def test_read_only_token_cannot_write_continuous_recording(self):
        response = CLIENT.post(
            f"/api/v1/cameras/{self.camera_id}/continuous-recording",
            headers=_auth(self.read_only_token),
            json={"enabled": True},
        )
        self.assertEqual(response.status_code, 403)

    def test_read_only_token_cannot_write_detection_settings(self):
        response = CLIENT.post(
            f"/api/v1/cameras/{self.camera_id}/detection",
            headers=_auth(self.read_only_token),
            json={"enabled": True},
        )
        self.assertEqual(response.status_code, 403)

    def test_control_token_can_toggle_recording_enabled(self):
        response = CLIENT.post(
            f"/api/v1/cameras/{self.camera_id}/recording",
            headers=_auth(self.control_token),
            json={"enabled": True, "duration_seconds": 45},
        )
        self.assertEqual(response.status_code, 200)
        camera = database.get_camera(main.SETTINGS.database_path, self.camera_id)
        self.assertTrue(camera["recording_enabled"])
        self.assertEqual(camera["recording_duration_seconds"], 45)

    def test_recording_write_is_a_partial_update(self):
        CLIENT.post(
            f"/api/v1/cameras/{self.camera_id}/recording",
            headers=_auth(self.control_token),
            json={"enabled": True, "duration_seconds": 45},
        )
        CLIENT.post(
            f"/api/v1/cameras/{self.camera_id}/recording",
            headers=_auth(self.control_token),
            json={"pre_seconds": 5},
        )
        camera = database.get_camera(main.SETTINGS.database_path, self.camera_id)
        # duration_seconds from the first call must survive the second,
        # narrower call.
        self.assertEqual(camera["recording_duration_seconds"], 45)
        self.assertEqual(camera["recording_pre_seconds"], 5)

    def test_control_token_can_toggle_continuous_recording(self):
        response = CLIENT.post(
            f"/api/v1/cameras/{self.camera_id}/continuous-recording",
            headers=_auth(self.control_token),
            json={"enabled": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["continuous_recording_enabled"])

    def test_detection_settings_read_returns_defaults_when_unset(self):
        response = CLIENT.get(
            f"/api/v1/cameras/{self.camera_id}/detection-settings",
            headers=_auth(self.read_only_token),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["enabled"])
        self.assertEqual(body["camera_id"], self.camera_id)

    def test_control_token_can_write_detection_settings(self):
        response = CLIENT.post(
            f"/api/v1/cameras/{self.camera_id}/detection",
            headers=_auth(self.control_token),
            json={"enabled": True, "confidence_threshold": 0.7},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["enabled"])
        self.assertEqual(body["confidence_threshold"], 0.7)

    def test_write_routes_record_audit_events_attributed_to_the_token(self):
        CLIENT.post(
            f"/api/v1/cameras/{self.camera_id}/recording",
            headers=_auth(self.control_token),
            json={"enabled": True},
        )
        events = database.list_audit_events(main.SETTINGS.database_path, action="camera.recording_toggled_via_api")
        self.assertEqual(events["total"], 1)
        self.assertEqual(events["events"][0]["username"], "api-token:control")

    def test_unknown_camera_returns_404_for_write_route(self):
        response = CLIENT.post(
            "/api/v1/cameras/999999/recording",
            headers=_auth(self.control_token),
            json={"enabled": True},
        )
        self.assertEqual(response.status_code, 404)


class ApiStreamAuthTests(unittest.TestCase):
    def setUp(self):
        _reset_database()
        _login()
        self.camera_id = _create_camera()
        self.token = _create_token("reader", can_control=False)

    def test_stream_playlist_requires_a_key(self):
        response = CLIENT.get(f"/api/v1/cameras/{self.camera_id}/stream/index.m3u8")
        self.assertEqual(response.status_code, 401)

    def test_stream_playlist_accepts_header_auth(self):
        response = CLIENT.get(
            f"/api/v1/cameras/{self.camera_id}/stream/index.m3u8",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        # Auth passed (not 401); the fake camera has no reachable stream, so
        # the route reports that instead.
        self.assertNotEqual(response.status_code, 401)

    def test_stream_playlist_accepts_query_param_auth(self):
        # ffmpeg/PyAV inside Home Assistant's stream integration fetches HLS
        # segment URLs directly with no way to attach a custom header, so
        # these three routes must also accept ?api_key=... .
        response = CLIENT.get(
            f"/api/v1/cameras/{self.camera_id}/stream/index.m3u8",
            params={"api_key": self.token},
        )
        self.assertNotEqual(response.status_code, 401)

    def test_stream_playlist_for_unknown_camera_is_404(self):
        response = CLIENT.get(
            "/api/v1/cameras/999999/stream/index.m3u8",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(response.status_code, 404)

    def test_stream_stop_requires_a_key(self):
        response = CLIENT.post(f"/api/v1/cameras/{self.camera_id}/stream/stop")
        self.assertEqual(response.status_code, 401)

    def test_stream_stop_succeeds_even_when_nothing_is_running(self):
        response = CLIENT.post(
            f"/api/v1/cameras/{self.camera_id}/stream/stop",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(response.status_code, 200)

    def test_stream_segment_rejects_non_ts_filenames(self):
        response = CLIENT.get(
            f"/api/v1/cameras/{self.camera_id}/stream/notasegment.txt",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
