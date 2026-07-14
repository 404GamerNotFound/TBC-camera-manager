import asyncio
import json
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.tbc import database
from app.tbc.mcp_server import build_mcp_app
from app.tbc.security import generate_api_key, hash_api_key
from app.tbc.snapshots import DashboardSnapshotManager

_JSON_RPC_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
_INITIALIZE_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"},
    },
}


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = self._tmp.name
        self.db_path = f"{tmp_dir}/tbc.sqlite3"
        database.initialize(self.db_path)
        self.camera_id = database.create_camera(
            self.db_path,
            name="Einfahrt",
            host="192.0.2.10",
            onvif_port=8000,
            http_port=80,
            username="admin",
            password="secret",
        )
        database.update_api_config(self.db_path, enabled=True, require_api_key=True)
        self.api_key = generate_api_key()
        database.set_api_key(self.db_path, key_hash=hash_api_key(self.api_key), key_prefix=self.api_key[:12])

        snapshot_manager = DashboardSnapshotManager(f"{tmp_dir}/snapshots", interval_seconds=600)
        mcp_app, session_cm = build_mcp_app(
            database_path=self.db_path,
            app_name="TBC",
            app_version="0.2.0",
            app_update_state={"update_available": False, "latest_version": None},
            snapshot_manager=snapshot_manager,
            snapshot_semaphore=asyncio.Semaphore(2),
            stream_uri_for=lambda camera: None,
        )
        app = FastAPI()
        app.mount("/mcp", mcp_app)

        @app.on_event("startup")
        async def _start():
            await session_cm.__aenter__()

        @app.on_event("shutdown")
        async def _stop():
            await session_cm.__aexit__(None, None, None)

        self._client_cm = TestClient(app)
        self.client = self._client_cm.__enter__()
        self.addCleanup(self._client_cm.__exit__, None, None, None)
        self.addCleanup(self._tmp.cleanup)

    def _auth_headers(self, key: str | None) -> dict[str, str]:
        headers = dict(_JSON_RPC_HEADERS)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _initialize(self, key: str | None):
        return self.client.post("/mcp/mcp", json=_INITIALIZE_BODY, headers=self._auth_headers(key))

    def _call_tool(self, name: str, arguments: dict, key: str | None = None):
        key = key if key is not None else self.api_key
        response = self.client.post(
            "/mcp/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
            headers=self._auth_headers(key),
        )
        line = next(line for line in response.text.splitlines() if line.startswith("data:"))
        return response.status_code, json.loads(line[len("data:"):].strip())

    def _list_tools(self, key: str | None = None):
        key = key if key is not None else self.api_key
        response = self.client.post(
            "/mcp/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers=self._auth_headers(key),
        )
        line = next(line for line in response.text.splitlines() if line.startswith("data:"))
        return json.loads(line[len("data:"):].strip())

    def test_initialize_without_key_is_rejected(self):
        response = self._initialize(None)
        self.assertEqual(response.status_code, 401)

    def test_initialize_with_wrong_key_is_rejected(self):
        response = self._initialize("wrong-key")
        self.assertEqual(response.status_code, 401)

    def test_initialize_with_correct_key_succeeds(self):
        response = self._initialize(self.api_key)
        self.assertEqual(response.status_code, 200)

    def test_api_disabled_rejects_even_correct_key(self):
        database.update_api_config(self.db_path, enabled=False, require_api_key=True)
        response = self._initialize(self.api_key)
        self.assertEqual(response.status_code, 404)

    def test_tools_list_exposes_all_eleven_tools(self):
        self._initialize(self.api_key)
        payload = self._list_tools()
        names = {tool["name"] for tool in payload["result"]["tools"]}
        self.assertEqual(
            names,
            {
                "list_cameras",
                "get_camera",
                "get_camera_detections",
                "get_camera_snapshot",
                "list_recordings",
                "get_recording",
                "get_recording_snapshot",
                "get_activity",
                "get_storage",
                "get_health",
                "get_status",
            },
        )

    def test_list_cameras_returns_seeded_camera(self):
        # FastMCP emits one `content` TextContent block per list item for list-returning
        # tools; the full array lives (JSON-object-wrapped, per MCP's structuredContent
        # convention) under structuredContent.result.
        self._initialize(self.api_key)
        status, payload = self._call_tool("list_cameras", {})
        self.assertEqual(status, 200)
        cameras = payload["result"]["structuredContent"]["result"]
        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0]["name"], "Einfahrt")
        self.assertEqual(cameras[0]["id"], self.camera_id)

    def test_get_status_reports_camera_count(self):
        self._initialize(self.api_key)
        status, payload = self._call_tool("get_status", {})
        self.assertEqual(status, 200)
        result = payload["result"]["structuredContent"]
        self.assertEqual(result["app_name"], "TBC")
        self.assertEqual(result["camera_count"], 1)

    def test_get_camera_not_found_reports_tool_error(self):
        self._initialize(self.api_key)
        status, payload = self._call_tool("get_camera", {"camera_id": 999})
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["isError"])
        self.assertIn("999", payload["result"]["content"][0]["text"])

    def test_get_recording_not_found_reports_tool_error(self):
        self._initialize(self.api_key)
        status, payload = self._call_tool("get_recording", {"recording_id": 42})
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["isError"])

    def test_list_recordings_excludes_continuous_and_returns_event_recording(self):
        rid = database.create_recording(
            self.db_path,
            camera_id=self.camera_id,
            storage_id=1,
            detection_key="ai_person",
            event_label="Person",
            storage_kind="local",
            started_at="2026-01-01T08:00:00",
        )
        database.update_recording_finished(
            self.db_path, rid, status="ready", duration_seconds=10, ended_at="2026-01-01T08:00:10"
        )
        continuous_id = database.create_recording(
            self.db_path,
            camera_id=self.camera_id,
            storage_id=1,
            detection_key="continuous",
            event_label="Dauer",
            storage_kind="local",
            started_at="2026-01-01T00:00:00",
        )
        database.update_recording_finished(
            self.db_path, continuous_id, status="ready", duration_seconds=3600, ended_at="2026-01-01T01:00:00"
        )

        self._initialize(self.api_key)
        status, payload = self._call_tool("list_recordings", {})
        self.assertEqual(status, 200)
        recordings = payload["result"]["structuredContent"]["result"]
        self.assertEqual(len(recordings), 1)
        self.assertEqual(recordings[0]["id"], rid)


if __name__ == "__main__":
    unittest.main()
