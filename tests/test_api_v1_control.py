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

import io
import json
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

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
from app.tbc.cloud_modules import CloudAccountField, CloudAccountFieldType  # noqa: E402
from app.tbc.plugin_requirements import PluginRequirementsInstallError  # noqa: E402

TOKEN_PATTERN = re.compile(r"tbc_[A-Za-z0-9_-]{20,}")

_client_cm = None
CLIENT: TestClient

_CSRF_TOKEN_RE = re.compile(r'<meta name="csrf-token" content="([^"]*)">')
_csrf_token = {"value": ""}


def _capture_csrf_token(response) -> None:
    response.read()
    match = _CSRF_TOKEN_RE.search(response.text)
    if match and match.group(1):
        _csrf_token["value"] = match.group(1)


def _attach_csrf_token(request) -> None:
    # Mirrors what static/i18n.js does in the browser: read the token
    # app.tbc.main's CSRF middleware minted into the session (exposed via
    # the <meta name="csrf-token"> tag on any rendered page) and send it
    # back as a header on state-changing requests.
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and _csrf_token["value"]:
        request.headers["X-CSRF-Token"] = _csrf_token["value"]


def setUpModule():
    global _client_cm, CLIENT
    _client_cm = TestClient(main.app)
    CLIENT = _client_cm.__enter__()
    CLIENT.event_hooks["request"].append(_attach_csrf_token)
    CLIENT.event_hooks["response"].append(_capture_csrf_token)


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

    def test_documentation_requires_login_and_renders_repository_markdown(self):
        CLIENT.post("/logout")
        unauthorized = CLIENT.get("/docs", follow_redirects=False)
        self.assertEqual(unauthorized.status_code, 303)
        self.assertEqual(unauthorized.headers["location"], "/login")

        _login()
        overview = CLIENT.get("/docs")
        api_reference = CLIENT.get("/docs/api.md")
        missing = CLIENT.get("/docs/missing.md")
        openapi_ui = CLIENT.get("/api/docs")

        self.assertEqual(overview.status_code, 200)
        self.assertIn('<h1 id="tbc-documentation">TBC documentation</h1>', overview.text)
        self.assertIn('href="/docs/user-guide.md"', overview.text)
        self.assertIn('href="/docs" data-i18n="docs.footer_link"', overview.text)
        self.assertEqual(api_reference.status_code, 200)
        self.assertIn('<article class="docs-article markdown-body">', api_reference.text)
        self.assertEqual(missing.status_code, 404)
        self.assertIn('data-i18n="docs.not_found"', missing.text)
        self.assertEqual(openapi_ui.status_code, 200)
        self.assertIn("Swagger UI", openapi_ui.text)

        CLIENT.post("/logout")
        database.create_user(
            main.SETTINGS.database_path,
            username="docs-viewer",
            password="viewerpass123",
            role="viewer",
        )
        CLIENT.post("/login", data={"username": "docs-viewer", "password": "viewerpass123"})
        viewer_overview = CLIENT.get("/docs")
        self.assertEqual(viewer_overview.status_code, 200)
        self.assertIn('href="/docs" data-i18n="docs.footer_link"', viewer_overview.text)
        self.assertNotIn('href="/license"', viewer_overview.text)
        self.assertNotIn("data-debug-toggle", viewer_overview.text)

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


class _FakeRunningProcess:
    """Stands in for a subprocess.Popen handle LIVE_MANAGER thinks is alive."""

    def poll(self):
        return None


class ApiStreamPlaylistRewriteTests(unittest.TestCase):
    """Regression coverage for the playlist auth-propagation bug: ffmpeg's HLS
    muxer writes bare segment filenames, and a client resolving those as
    relative URLs against the playlist's own URL does NOT carry the
    playlist's ?api_key=... query string forward (RFC 3986 5.3). Home
    Assistant's stream integration fetches segments with no custom headers,
    so every segment request came back 401 and the stream never played
    until the playlist route started rewriting segment references into
    full, self-authenticating URLs.

    Pre-seeds the playlist/segment files LIVE_MANAGER would otherwise
    produce via ffmpeg, so this doesn't depend on a real camera or ffmpeg
    process being available in CI.
    """

    def setUp(self):
        _reset_database()
        _login()
        self.camera_id = _create_camera()
        self.token = _create_token("reader", can_control=False)
        self.live_key = f"api-camera-{self.camera_id}"
        self.out_dir = Path(main.SETTINGS.live_path) / self.live_key
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "segment000.ts").write_bytes(b"fake-ts-bytes-0")
        (self.out_dir / "segment001.ts").write_bytes(b"fake-ts-bytes-1")
        (self.out_dir / "index.m3u8").write_text(
            "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n"
            "#EXTINF:2.000000,\nsegment000.ts\n#EXTINF:2.000000,\nsegment001.ts\n"
        )
        # Pretending a process is already running for this key makes
        # LiveManager.status()/wait_until_ready() treat the stream as live
        # without touching out_dir. LiveManager.start() itself is mocked out
        # below rather than relied on to short-circuit here: it checks
        # shutil.which("ffmpeg") unconditionally before it ever looks at
        # self._processes, so it would raise "ffmpeg is not installed" on a
        # CI runner without ffmpeg even with a fake process already in
        # place - this test only cares about the playlist route's rewriting
        # logic, not about actually invoking ffmpeg.
        main.LIVE_MANAGER._processes[self.live_key] = _FakeRunningProcess()

    def tearDown(self):
        main.LIVE_MANAGER._processes.pop(self.live_key, None)
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def _get_playlist(self, **headers):
        with (
            patch("app.tbc.main.stream_uri_for", return_value="rtsp://fake/stream"),
            patch("app.tbc.main._camera_supports", return_value=True),
            patch.object(main.LIVE_MANAGER, "start"),
        ):
            return CLIENT.get(f"/api/v1/cameras/{self.camera_id}/stream/index.m3u8", headers=headers)

    def test_segment_references_are_absolute_and_carry_the_api_key(self):
        response = self._get_playlist(Authorization=f"Bearer {self.token}")
        self.assertEqual(response.status_code, 200)
        segment_lines = [line for line in response.text.splitlines() if line and not line.startswith("#")]
        self.assertEqual(len(segment_lines), 2)
        for line in segment_lines:
            self.assertTrue(line.startswith("http://"), line)
            self.assertIn(f"?api_key={self.token}", line)

    def test_rewritten_segment_urls_are_fetchable_exactly_as_returned(self):
        response = self._get_playlist(Authorization=f"Bearer {self.token}")
        segment_lines = [line for line in response.text.splitlines() if line and not line.startswith("#")]
        expected_bytes = {b"fake-ts-bytes-0", b"fake-ts-bytes-1"}
        for line in segment_lines:
            parts = urlsplit(line)
            relative = f"{parts.path}?{parts.query}"
            segment_response = CLIENT.get(relative)
            self.assertEqual(segment_response.status_code, 200)
            self.assertIn(segment_response.content, expected_bytes)

    def test_segment_fetch_without_the_query_param_is_rejected(self):
        # This is exactly the failure mode that broke playback in Home
        # Assistant before the playlist rewrite: a bare relative segment
        # request, with no credentials attached at all.
        response = CLIENT.get(f"/api/v1/cameras/{self.camera_id}/stream/segment000.ts")
        self.assertEqual(response.status_code, 401)


class _FakeXSenseCloudModule:
    key = "xsense-cloud"
    label = "X-Sense"
    account_username_field = "email"
    account_password_field = "password"
    account_fields = (
        CloudAccountField(key="email", label="Email", field_type=CloudAccountFieldType.EMAIL),
        CloudAccountField(key="password", label="Password", field_type=CloudAccountFieldType.PASSWORD),
    )


class CloudDeviceCredentialCarryoverImportTests(unittest.TestCase):
    """POST /cloud-accounts/{id}/devices/import for CloudDevice(needs_account_credentials=True)
    devices - see app.tbc.cloud_modules.base.CloudDevice for why this exists
    (X-Sense-style cloud providers with no manual_stream_uri, but whose
    suggested CameraModule can reuse the cloud account's own credentials).

    Lives in this file (rather than its own) because only one test module in
    the suite may own app.tbc.main's TestClient - see this file's docstring.
    """

    def setUp(self):
        db_path = main.SETTINGS.database_path
        if os.path.exists(db_path):
            os.remove(db_path)
        database.initialize(db_path, main.SETTINGS.recordings_path)
        database.ensure_admin_user(db_path, main.SETTINGS.admin_username, main.SETTINGS.admin_password)
        CLIENT.post("/login", data={"username": "admin", "password": "adminpass123"})

    def test_add_as_camera_reuses_the_cloud_account_s_own_credentials(self):
        with patch("app.tbc.routers.cloud_accounts.get_cloud_module", return_value=_FakeXSenseCloudModule()):
            account_id = database.create_cloud_account(
                main.SETTINGS.database_path,
                module_key="xsense-cloud",
                label="Home",
                config={"email": "user@example.com", "password": "SuperSecretPW123"},
                sensitive_keys=("password",),
            )
            response = CLIENT.post(
                f"/cloud-accounts/{account_id}/devices/import",
                data={"name": "Smart-Kamera", "external_id": "AICFJ3SUJHS4306", "module_key": "rtsp_only"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        cameras = database.list_cameras(main.SETTINGS.database_path)
        self.assertEqual(len(cameras), 1)
        camera = cameras[0]
        self.assertEqual(camera["name"], "Smart-Kamera")
        self.assertEqual(camera["host"], "AICFJ3SUJHS4306")
        self.assertEqual(camera["username"], "user@example.com")
        self.assertEqual(camera["password"], "SuperSecretPW123")
        self.assertEqual(camera.get("manual_stream_uri") or "", "")

    def test_import_without_manual_stream_uri_or_external_id_is_rejected(self):
        with patch("app.tbc.routers.cloud_accounts.get_cloud_module", return_value=_FakeXSenseCloudModule()):
            account_id = database.create_cloud_account(
                main.SETTINGS.database_path,
                module_key="xsense-cloud",
                label="Home",
                config={"email": "user@example.com", "password": "secret"},
                sensitive_keys=("password",),
            )
            response = CLIENT.post(
                f"/cloud-accounts/{account_id}/devices/import",
                data={"name": "Smart-Kamera", "module_key": "rtsp_only"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(database.list_cameras(main.SETTINGS.database_path), [])

    def test_import_is_rejected_when_module_has_not_declared_credential_fields(self):
        class _ModuleWithoutCredentialFields(_FakeXSenseCloudModule):
            account_username_field = None
            account_password_field = None

        with patch("app.tbc.routers.cloud_accounts.get_cloud_module", return_value=_ModuleWithoutCredentialFields()):
            account_id = database.create_cloud_account(
                main.SETTINGS.database_path,
                module_key="xsense-cloud",
                label="Home",
                config={"email": "user@example.com", "password": "secret"},
                sensitive_keys=("password",),
            )
            response = CLIENT.post(
                f"/cloud-accounts/{account_id}/devices/import",
                data={"name": "Smart-Kamera", "external_id": "AICFJ3SUJHS4306", "module_key": "rtsp_only"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(database.list_cameras(main.SETTINGS.database_path), [])


class NetworkTopologyTests(unittest.TestCase):
    """_network_topology() groups mapped cameras by network account, then by
    the switch/AP they're connected through - a real (account -> uplink ->
    camera) tree for the "Network mappings" page. See database.py's
    network_device_status/network_device_events for how offline cameras
    still resolve a last-known uplink here instead of vanishing from the
    tree.

    Lives in this file (rather than its own) because only one test module in
    the suite may own app.tbc.main's TestClient - see this file's docstring.
    """

    def test_groups_cameras_by_account_then_uplink_sorted_alphabetically(self):
        mapped = [
            {
                "camera": {"id": 1, "name": "Pool"},
                "account": {"id": 1, "label": "Unifi Home"},
                "state": {"uplink_name": "Schuppen PoE", "online": True},
                "last_status": None,
                "events": [],
            },
            {
                "camera": {"id": 2, "name": "Terasse"},
                "account": {"id": 1, "label": "Unifi Home"},
                "state": {"uplink_name": "Schuppen - U7 Long-Range", "online": False},
                "last_status": None,
                "events": [],
            },
            {
                "camera": {"id": 3, "name": "Einfahrt"},
                "account": {"id": 1, "label": "Unifi Home"},
                "state": {"uplink_name": "Schuppen PoE", "online": True},
                "last_status": None,
                "events": [],
            },
        ]

        topology = main._network_topology(mapped)

        self.assertEqual(len(topology), 1)
        account_node = topology[0]
        self.assertEqual(account_node["account_label"], "Unifi Home")
        self.assertEqual(account_node["total_cameras"], 3)
        self.assertEqual(
            [group["uplink_name"] for group in account_node["groups"]],
            ["Schuppen - U7 Long-Range", "Schuppen PoE"],
        )
        schuppen_poe = next(g for g in account_node["groups"] if g["uplink_name"] == "Schuppen PoE")
        self.assertEqual([entry["camera"]["name"] for entry in schuppen_poe["cameras"]], ["Pool", "Einfahrt"])

    def test_cameras_without_any_known_uplink_are_omitted(self):
        mapped = [
            {
                "camera": {"id": 1, "name": "Pool"},
                "account": {"id": 1, "label": "Unifi Home"},
                "state": {"uplink_name": "Schuppen PoE", "online": True},
                "last_status": None,
                "events": [],
            },
            {
                "camera": {"id": 2, "name": "Flur"},
                "account": {"id": 1, "label": "Unifi Home"},
                "state": None,
                "last_status": None,
                "events": [],
            },
        ]

        topology = main._network_topology(mapped)

        self.assertEqual(len(topology), 1)
        self.assertEqual(topology[0]["total_cameras"], 1)

    def test_offline_camera_falls_back_to_last_known_uplink(self):
        mapped = [
            {
                "camera": {"id": 1, "name": "Pool"},
                "account": {"id": 1, "label": "Unifi Home"},
                "state": None,
                "last_status": {"online": False, "uplink_name": "Schuppen PoE", "connection_type": "wired"},
                "events": [{"online": False, "uplink_name": "Schuppen PoE", "created_at": "2026-07-19T06:00:00+00:00"}],
            },
        ]

        topology = main._network_topology(mapped)

        camera_entry = topology[0]["groups"][0]["cameras"][0]
        self.assertFalse(camera_entry["online"])
        self.assertEqual(camera_entry["uplink_name"], "Schuppen PoE")
        self.assertEqual(camera_entry["last_seen"], "2026-07-19T06:00:00+00:00")

    def test_network_mappings_page_renders_the_topology_tree(self):
        db_path = main.SETTINGS.database_path
        if os.path.exists(db_path):
            os.remove(db_path)
        database.initialize(db_path, main.SETTINGS.recordings_path)
        database.ensure_admin_user(db_path, main.SETTINGS.admin_username, main.SETTINGS.admin_password)
        CLIENT.post("/login", data={"username": "admin", "password": "adminpass123"})

        account_id = database.create_network_account(
            db_path, module_key="unifi-network", label="Home", config={"host": "10.0.0.1", "identifier": "admin", "secret": "secret"}
        )
        camera_id = database.create_camera(
            db_path, name="Einfahrt", host="", onvif_port=8000, http_port=80, username="", password=""
        )
        database.set_camera_network_mapping(db_path, camera_id, network_account_id=account_id, mac="ec:71:db:a3:ee:17")
        main.NETWORK_STATE_CACHE[account_id] = [
            {
                "mac_address": "ec:71:db:a3:ee:17",
                "name": "Einfahrt",
                "ip_address": "10.0.0.20",
                "online": True,
                "connection_type": "wired",
                "uplink_name": "Schuppen PoE",
                "signal_dbm": None,
                "last_seen": "2026-07-19T07:31:05+00:00",
            }
        ]
        main._record_network_device_status(account_id, main.NETWORK_STATE_CACHE[account_id])

        response = CLIENT.get("/network-mappings")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Schuppen PoE", response.text)
        self.assertIn("Home", response.text)
        self.assertIn("topology-tree", response.text)
        self.assertIn("topology-camera-log", response.text)

    def test_offline_camera_shows_last_connected_hint_on_the_page(self):
        db_path = main.SETTINGS.database_path
        if os.path.exists(db_path):
            os.remove(db_path)
        database.initialize(db_path, main.SETTINGS.recordings_path)
        database.ensure_admin_user(db_path, main.SETTINGS.admin_username, main.SETTINGS.admin_password)
        CLIENT.post("/login", data={"username": "admin", "password": "adminpass123"})

        account_id = database.create_network_account(
            db_path, module_key="unifi-network", label="Home", config={"host": "10.0.0.1", "identifier": "admin", "secret": "secret"}
        )
        camera_id = database.create_camera(
            db_path, name="Pool", host="", onvif_port=8000, http_port=80, username="", password=""
        )
        database.set_camera_network_mapping(db_path, camera_id, network_account_id=account_id, mac="ec:71:db:80:98:59")
        main.NETWORK_STATE_CACHE[account_id] = [
            {
                "mac_address": "ec:71:db:80:98:59", "name": "Pool", "ip_address": "10.0.0.30", "online": True,
                "connection_type": "wired", "uplink_name": "Schuppen PoE", "signal_dbm": None, "last_seen": None,
            }
        ]
        main._record_network_device_status(account_id, main.NETWORK_STATE_CACHE[account_id])
        # Second probe: the camera dropped out of the controller's client list entirely.
        main.NETWORK_STATE_CACHE[account_id] = []
        main._record_network_device_status(account_id, main.NETWORK_STATE_CACHE[account_id])

        response = CLIENT.get("/network-mappings")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Schuppen PoE", response.text)
        self.assertIn("network_account.last_connected_at", response.text)


class PluginRequirementsFlowTests(unittest.TestCase):
    """POST /camera-modules/import redirects to /plugin-requirements/confirm
    when a plugin declares a pip requirement that isn't installed (see
    app.tbc.plugin_requirements), and POST /plugin-requirements/install (pip
    mocked out) lets the admin install it and retry.

    Lives in this file (rather than its own) because only one test module in
    the suite may own app.tbc.main's TestClient - see this file's docstring.
    Uses the camera-modules import route (not network/cloud) because only
    TBC_CAMERA_MODULES_PATH is pointed at a writable temp dir by this
    module's env setup above.
    """

    def setUp(self):
        db_path = main.SETTINGS.database_path
        if os.path.exists(db_path):
            os.remove(db_path)
        database.initialize(db_path, main.SETTINGS.recordings_path)
        database.ensure_admin_user(db_path, main.SETTINGS.admin_username, main.SETTINGS.admin_password)
        CLIENT.post("/login", data={"username": "admin", "password": "adminpass123"})

    def _camera_plugin_zip(self, *, requirements):
        manifest = {
            "schema_version": 1,
            "key": "acme_requirements_camera",
            "label": "Acme Requirements Camera",
            "version": "1.0.0",
            "description": "",
            "entrypoint": "plugin.py",
            "capabilities": ["live"],
            "requirements": requirements,
        }
        plugin_code = (
            "from tbc_camera_api import CameraModule, CameraSnapshot\n\n"
            "class AcmeModule(CameraModule):\n"
            "    async def probe(self, camera):\n"
            "        return CameraSnapshot(status='ok', message='Acme')\n\n"
            "def create_module():\n"
            "    return AcmeModule()\n"
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest))
            bundle.writestr("plugin.py", plugin_code)
        return output.getvalue()

    def test_import_with_missing_requirement_redirects_to_confirm_page(self):
        archive = self._camera_plugin_zip(requirements=["definitely-not-a-real-package-xyz==1.0"])

        response = CLIENT.post(
            "/camera-modules/import",
            files={"plugin_file": ("plugin.zip", archive, "application/zip")},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("/plugin-requirements/confirm", response.headers["location"])
        self.assertIn("definitely-not-a-real-package-xyz", response.headers["location"])

    def test_confirm_page_renders_the_missing_packages_and_label(self):
        response = CLIENT.get(
            "/plugin-requirements/confirm",
            params={
                "requirements": ["definitely-not-a-real-package-xyz==1.0"],
                "retry_url": "/camera-modules",
                "label": "Acme Requirements Camera",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("definitely-not-a-real-package-xyz==1.0", response.text)
        self.assertIn("Acme Requirements Camera", response.text)

    def test_confirm_page_rejects_an_external_retry_url(self):
        response = CLIENT.get(
            "/plugin-requirements/confirm",
            params={"requirements": ["pkg==1.0"], "retry_url": "https://evil.example/steal"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("https://evil.example", response.text)

    def test_install_now_calls_pip_and_redirects_to_retry_url(self):
        with patch("app.tbc.routers.plugins.install_requirements", new=AsyncMock(return_value="Successfully installed")):
            response = CLIENT.post(
                "/plugin-requirements/install",
                data={"requirements": ["definitely-not-a-real-package-xyz==1.0"], "retry_url": "/camera-modules"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/camera-modules")

    def test_install_now_refreshes_cameras_already_on_that_module(self):
        # Regression test: a camera already configured on a plugin that was
        # missing a requirement (e.g. Reolink without reolink-aio) used to
        # keep showing a stale "library not installed" probe result on its
        # detail page until the next background poll cycle or a manual
        # "Refresh" click - now it's re-probed immediately once the missing
        # package is actually installed.
        camera_id = database.create_camera(
            main.SETTINGS.database_path,
            name="Front",
            host="203.0.113.5",
            onvif_port=8000,
            http_port=80,
            username="admin",
            password="secret",
            module_key="acme_requirements_camera",
        )
        other_camera_id = database.create_camera(
            main.SETTINGS.database_path,
            name="Back",
            host="203.0.113.6",
            onvif_port=8000,
            http_port=80,
            username="admin",
            password="secret",
            module_key="standard_onvif",
        )

        with (
            patch("app.tbc.routers.plugins.install_requirements", new=AsyncMock(return_value="Successfully installed")),
            patch("app.tbc.routers.plugins._refresh_camera", new=AsyncMock()) as refresh_mock,
        ):
            response = CLIENT.post(
                "/plugin-requirements/install",
                data={
                    "requirements": ["definitely-not-a-real-package-xyz==1.0"],
                    "retry_url": "/camera-modules",
                    "plugin_kind": "camera",
                    "module_key": "acme_requirements_camera",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        refresh_mock.assert_called_once_with(camera_id)
        self.assertNotIn(unittest.mock.call(other_camera_id), refresh_mock.call_args_list)

    def test_install_now_without_module_key_does_not_refresh_any_camera(self):
        database.create_camera(
            main.SETTINGS.database_path,
            name="Front",
            host="203.0.113.5",
            onvif_port=8000,
            http_port=80,
            username="admin",
            password="secret",
            module_key="acme_requirements_camera",
        )

        with (
            patch("app.tbc.routers.plugins.install_requirements", new=AsyncMock(return_value="Successfully installed")),
            patch("app.tbc.routers.plugins._refresh_camera", new=AsyncMock()) as refresh_mock,
        ):
            CLIENT.post(
                "/plugin-requirements/install",
                data={"requirements": ["definitely-not-a-real-package-xyz==1.0"], "retry_url": "/camera-modules"},
                follow_redirects=False,
            )

        refresh_mock.assert_not_called()

    def test_install_now_failure_flashes_and_redirects_back(self):
        with patch(
            "app.tbc.routers.plugins.install_requirements",
            new=AsyncMock(side_effect=PluginRequirementsInstallError("ERROR: no matching distribution")),
        ):
            response = CLIENT.post(
                "/plugin-requirements/install",
                data={"requirements": ["definitely-not-a-real-package-xyz==1.0"], "retry_url": "/camera-modules"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/camera-modules")

    def test_confirm_page_includes_source_id_hidden_field_when_present(self):
        response = CLIENT.get(
            "/plugin-requirements/confirm",
            params={
                "requirements": ["definitely-not-a-real-package-xyz==1.0"],
                "retry_url": "/updates",
                "label": "Acme Requirements Camera",
                "source_id": 42,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('name="source_id" value="42"', response.text)

    def test_confirm_page_omits_source_id_field_when_absent(self):
        # A ZIP-upload origin (no source_id) can't be auto-retried - there's
        # no archive left to re-run install_plugin_archive() against.
        response = CLIENT.get(
            "/plugin-requirements/confirm",
            params={"requirements": ["pkg==1.0"], "retry_url": "/camera-modules"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('name="source_id"', response.text)

    def test_install_now_with_source_id_retries_the_sync_instead_of_just_redirecting(self):
        # Regression test: previously, confirming a missing-requirement
        # install from the Updates/plugin-sources GitHub-sync flow just
        # bounced back to a passive listing page that still showed the
        # update as pending, forcing the admin to manually click "Update
        # now" again - each retry burning another unauthenticated GitHub API
        # call. Now the same source is retried automatically.
        source_id = database.create_plugin_source(
            main.SETTINGS.database_path,
            plugin_kind="camera",
            label="Acme Retry Camera",
            repo_url="https://github.com/example/acme-retry",
            ref="main",
            subdirectory="",
        )
        archive = self._camera_plugin_zip(requirements=[])
        with (
            patch("app.tbc.routers.plugins.install_requirements", new=AsyncMock(return_value="Successfully installed")),
            patch("app.tbc.main.resolve_and_fetch_plugin", return_value=(archive, "abc123")) as fetch_mock,
        ):
            response = CLIENT.post(
                "/plugin-requirements/install",
                data={
                    "requirements": ["definitely-not-a-real-package-xyz==1.0"],
                    "retry_url": "/updates",
                    "source_id": source_id,
                },
                follow_redirects=False,
            )

        fetch_mock.assert_called_once()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/updates")
        source = database.get_plugin_source(main.SETTINGS.database_path, source_id)
        self.assertEqual(source["last_sync_status"], "ok")


class HomeAssistantIngressTests(unittest.TestCase):
    """Home Assistant Ingress sends the dynamic per-installation path prefix
    as an X-Ingress-Path request header (not stripped before forwarding) -
    see app/tbc/ingress.py. Every redirect, the session cookie, rendered
    page links, and JSON API URLs must carry that prefix when it's present,
    and must be byte-for-byte unaffected when it's absent (plain Docker, or
    Home Assistant without Ingress - today's only supported access path).
    """

    INGRESS_PATH = "/api/hassio_ingress/abc123"

    def setUp(self):
        db_path = main.SETTINGS.database_path
        if os.path.exists(db_path):
            os.remove(db_path)
        database.initialize(db_path, main.SETTINGS.recordings_path)
        database.ensure_admin_user(db_path, main.SETTINGS.admin_username, main.SETTINGS.admin_password)

    def test_redirect_location_is_prefixed_under_ingress(self):
        response = CLIENT.post(
            "/login",
            data={"username": "admin", "password": "adminpass123"},
            headers={"X-Ingress-Path": self.INGRESS_PATH},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"{self.INGRESS_PATH}/cameras")

    def test_redirect_location_is_unprefixed_without_ingress_header(self):
        response = CLIENT.post(
            "/login",
            data={"username": "admin", "password": "adminpass123"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/cameras")

    def test_session_cookie_path_is_prefixed_under_ingress(self):
        response = CLIENT.post(
            "/login",
            data={"username": "admin", "password": "adminpass123"},
            headers={"X-Ingress-Path": self.INGRESS_PATH},
            follow_redirects=False,
        )

        set_cookie_headers = response.headers.get_list("set-cookie")
        session_cookie = next(header for header in set_cookie_headers if header.startswith("session="))
        self.assertIn(f"Path={self.INGRESS_PATH}/", session_cookie)

    def test_session_cookie_path_is_unprefixed_without_ingress_header(self):
        response = CLIENT.post(
            "/login",
            data={"username": "admin", "password": "adminpass123"},
            follow_redirects=False,
        )

        set_cookie_headers = response.headers.get_list("set-cookie")
        session_cookie = next(header for header in set_cookie_headers if header.startswith("session="))
        # Untouched Starlette SessionMiddleware output uses lowercase "path=".
        self.assertIn("path=/;", session_cookie)

    def test_rendered_page_links_and_js_global_are_prefixed_under_ingress(self):
        CLIENT.post("/login", data={"username": "admin", "password": "adminpass123"})

        response = CLIENT.get("/cameras", headers={"X-Ingress-Path": self.INGRESS_PATH})

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'href="{self.INGRESS_PATH}/cameras"', response.text)
        self.assertIn(f'window.TBC_INGRESS_PREFIX = "{self.INGRESS_PATH}";', response.text)
        # Regression guard: static asset URLs (built from a plain manual path,
        # not Starlette's url_for()/root_path) must come out as a single clean
        # prefixed relative path, e.g. "/api/.../static/i18n.js" - not a
        # mangled "{prefix}{absolute_url}" concatenation - see app/tbc/ingress.py
        # for why url_for()+root_path was abandoned for this.
        self.assertIn(f'src="{self.INGRESS_PATH}/static/i18n.js', response.text)
        self.assertNotIn("http://testserver/static", response.text)

    def test_static_files_are_reachable_under_ingress(self):
        # Regression test for the actual bug this was shipped with: setting
        # ASGI scope["root_path"] made Starlette's Mount routing (used by the
        # /static StaticFiles mount) look for a doubled "static/static/..."
        # path and 404 - see app/tbc/ingress.py's module docstring. Home
        # Assistant Supervisor strips the ingress prefix from the path before
        # forwarding to the container, so the request TBC actually receives
        # is the bare path below, with only the X-Ingress-Path header set.
        response = CLIENT.get("/static/i18n.js", headers={"X-Ingress-Path": self.INGRESS_PATH})

        self.assertEqual(response.status_code, 200)

    def test_rendered_page_links_are_unprefixed_without_ingress_header(self):
        CLIENT.post("/login", data={"username": "admin", "password": "adminpass123"})

        response = CLIENT.get("/cameras")

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/cameras"', response.text)
        self.assertIn('window.TBC_INGRESS_PREFIX = "";', response.text)

    def test_live_status_api_json_urls_are_prefixed_under_ingress(self):
        CLIENT.post("/login", data={"username": "admin", "password": "adminpass123"})

        response = CLIENT.get("/api/live/status", headers={"X-Ingress-Path": self.INGRESS_PATH})

        self.assertEqual(response.status_code, 200)
        for item in response.json()["items"]:
            self.assertTrue(item["playlist_url"].startswith(self.INGRESS_PATH + "/"))
            self.assertTrue(item["webrtc_offer_url"].startswith(self.INGRESS_PATH + "/"))


class InvalidSessionRecoveryTests(unittest.TestCase):
    """A session cookie can outlive the account it points at - e.g. an admin
    deletes a user, or someone restores an older database backup, while that
    user's browser still holds a valid, unexpired session. Regression test for
    the resulting bug: every route that reaches this state used to raise an
    uncaught exception (a plain-text 500, not JSON), which is what surfaced in
    the browser as e.g. the live view's generic "Live-API could not be loaded"
    fallback instead of a clean re-login.
    """

    def setUp(self):
        _reset_database()
        _login()
        self.admin_id = next(
            user["id"] for user in database.list_users(main.SETTINGS.database_path) if user["username"] == "admin"
        )
        database.delete_user(main.SETTINGS.database_path, self.admin_id)

    def test_api_route_returns_json_401_instead_of_a_bare_500(self):
        response = CLIENT.get("/api/live/status")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "unauthorized"})

    def test_page_route_redirects_to_login_instead_of_a_bare_500(self):
        response = CLIENT.get("/cameras", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_session_is_cleared_so_a_fresh_login_works_afterward(self):
        CLIENT.get("/cameras", follow_redirects=False)
        database.ensure_admin_user(main.SETTINGS.database_path, main.SETTINGS.admin_username, main.SETTINGS.admin_password)
        response = CLIENT.post("/login", data={"username": "admin", "password": "adminpass123"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/cameras")

if __name__ == "__main__":
    unittest.main()
