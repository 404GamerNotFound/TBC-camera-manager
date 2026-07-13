import sys
import types
import unittest
from unittest.mock import patch

from app.tbc.cloud_modules import CloudConnectionError
from app.tbc.cloud_plugins.unifi_protect.module import UnifiProtectCloudModule


class FakeChannel:
    def __init__(self, is_rtsp_enabled, rtsp_url):
        self.is_rtsp_enabled = is_rtsp_enabled
        self.rtsp_url = rtsp_url


class FakeCamera:
    def __init__(self, camera_id, name, market_name, camera_type, is_connected, channels):
        self.id = camera_id
        self.name = name
        self.market_name = market_name
        self.type = camera_type
        self.is_connected = is_connected
        self.channels = channels


class FakeNvr:
    name = "Zuhause NVR"
    version = "4.0.21"


class FakeBootstrap:
    def __init__(self, cameras):
        self.cameras = cameras
        self.nvr = FakeNvr()


def _default_cameras():
    return {
        "cam1": FakeCamera(
            "cam1", "Eingang", "G4 Pro", "G4Pro", True, [FakeChannel(True, "rtsp://10.0.0.5:7447/abc123")]
        ),
        "cam2": FakeCamera("cam2", "Garage", "G4 Instant", "G4Instant", False, [FakeChannel(False, None)]),
    }


class FakeProtectApiClient:
    instance = None

    def __init__(self, host, port, username, password, verify_ssl=True, store_sessions=True, **kwargs):
        type(self).instance = self
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.closed = False
        self._bootstrap = FakeBootstrap(_default_cameras())

    async def update(self):
        return self._bootstrap

    async def close_session(self):
        self.closed = True


class FakeNotAuthorizedClient(FakeProtectApiClient):
    async def update(self):
        raise _FakeNotAuthorized("wrong password")


class _FakeUnifiProtectError(Exception):
    pass


class _FakeNotAuthorized(PermissionError, _FakeUnifiProtectError):
    pass


class UnifiProtectModuleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.account = {
            "host": "10.0.0.1",
            "port": 443,
            "identifier": "admin",
            "secret": "secret",
            "verify_ssl": False,
        }
        uiprotect_module = types.ModuleType("uiprotect")
        uiprotect_module.ProtectApiClient = FakeProtectApiClient
        exceptions_module = types.ModuleType("uiprotect.exceptions")
        exceptions_module.NotAuthorized = _FakeNotAuthorized
        exceptions_module.UnifiProtectError = _FakeUnifiProtectError
        self._patcher = patch.dict(
            sys.modules,
            {"uiprotect": uiprotect_module, "uiprotect.exceptions": exceptions_module},
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.module = UnifiProtectCloudModule()

    async def test_test_connection_reports_nvr_and_camera_count(self):
        message = await self.module.test_connection(self.account)

        self.assertIn("Zuhause NVR", message)
        self.assertIn("2 Kamera(s)", message)
        self.assertTrue(FakeProtectApiClient.instance.closed)

    async def test_test_connection_wraps_auth_failure(self):
        with patch("uiprotect.ProtectApiClient", FakeNotAuthorizedClient):
            with self.assertRaisesRegex(CloudConnectionError, "Benutzername oder Passwort"):
                await self.module.test_connection(self.account)

    async def test_discover_devices_resolves_rtsp_url_for_enabled_channel_only(self):
        devices = await self.module.discover_devices(self.account)

        self.assertEqual(len(devices), 2)
        by_name = {device.name: device for device in devices}
        self.assertEqual(by_name["Eingang"].manual_stream_uri, "rtsp://10.0.0.5:7447/abc123")
        self.assertEqual(by_name["Eingang"].suggested_module_key, "ubiquiti")
        self.assertTrue(by_name["Eingang"].online)
        self.assertIsNone(by_name["Garage"].manual_stream_uri)
        self.assertFalse(by_name["Garage"].online)
        self.assertTrue(FakeProtectApiClient.instance.closed)

    async def test_discover_devices_wraps_connection_failure(self):
        with patch("uiprotect.ProtectApiClient", FakeNotAuthorizedClient):
            with self.assertRaises(CloudConnectionError):
                await self.module.discover_devices(self.account)

    async def test_missing_host_raises_before_import(self):
        with self.assertRaisesRegex(CloudConnectionError, "Host ist erforderlich"):
            await self.module.test_connection({**self.account, "host": ""})


class UnifiProtectModuleWithoutLibraryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._patcher = patch.dict(sys.modules, {"uiprotect": None})
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.module = UnifiProtectCloudModule()

    async def test_missing_library_is_reported_gracefully(self):
        account = {"host": "10.0.0.1", "port": 443, "identifier": "admin", "secret": "secret"}
        with self.assertRaisesRegex(CloudConnectionError, "nicht installiert"):
            await self.module.test_connection(account)


if __name__ == "__main__":
    unittest.main()
