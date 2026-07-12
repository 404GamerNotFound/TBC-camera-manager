import sys
import types
import unittest
from unittest.mock import patch

from app.tbc.cloud_modules import CloudConnectionError
from app.tbc.cloud_plugins.eufy.module import EufyCloudModule


class FakeCamera:
    def __init__(self, serial, name, model, ip_address=None):
        self.serial = serial
        self.name = name
        self.model = model
        self.ip_address = ip_address


class FakeApi:
    def __init__(self):
        self.cameras = {
            "cam1": FakeCamera("cam1", "Eingang", "EufyCam 3", "192.168.1.25"),
            "cam2": FakeCamera("cam2", "Garten", "SoloCam S340"),
        }
        self.stations = {"station1": object()}


class FakeClientSession:
    last_instance = None

    def __init__(self):
        type(self).last_instance = self
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.closed = True


class FakeInvalidCredentialsError(Exception):
    pass


class FakeCaptchaRequiredError(Exception):
    pass


class EufyCloudModuleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.login_calls = []

        async def async_login(email, password, session, country="US"):
            self.login_calls.append((email, password, session, country))
            return FakeApi()

        aiohttp_module = types.ModuleType("aiohttp")
        aiohttp_module.ClientSession = FakeClientSession
        eufy_module = types.ModuleType("eufy_security")
        eufy_module.async_login = async_login
        eufy_module.InvalidCredentialsError = FakeInvalidCredentialsError
        eufy_module.CaptchaRequiredError = FakeCaptchaRequiredError
        self._patcher = patch.dict(
            sys.modules,
            {"aiohttp": aiohttp_module, "eufy_security": eufy_module},
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.module = EufyCloudModule()
        self.account = {
            "email": "guest@example.com",
            "password": "secret",
            "country": "DE",
            "rtsp_username": "nas user",
            "rtsp_password": "p@ss/word",
        }

    async def test_connection_reports_camera_and_station_count(self):
        message = await self.module.test_connection(self.account)

        self.assertIn("2 Kamera(s)", message)
        self.assertIn("1 Station(en)", message)
        self.assertEqual(self.login_calls[0][3], "DE")
        self.assertTrue(FakeClientSession.last_instance.closed)

    async def test_discovery_only_exposes_stable_local_rtsp_urls(self):
        devices = await self.module.discover_devices(self.account)

        by_name = {device.name: device for device in devices}
        self.assertEqual(
            by_name["Eingang"].manual_stream_uri,
            "rtsp://nas%20user:p%40ss%2Fword@192.168.1.25:554/live0",
        )
        self.assertEqual(by_name["Eingang"].suggested_module_key, "rtsp_only")
        self.assertIsNone(by_name["Garten"].manual_stream_uri)

    async def test_discovery_without_rtsp_credentials_does_not_start_cloud_stream(self):
        devices = await self.module.discover_devices(
            {**self.account, "rtsp_username": "", "rtsp_password": ""}
        )

        self.assertTrue(all(device.manual_stream_uri is None for device in devices))

    async def test_invalid_credentials_are_reported_in_german(self):
        async def failing_login(*args, **kwargs):
            raise FakeInvalidCredentialsError("bad password")

        with patch("eufy_security.async_login", failing_login):
            with self.assertRaisesRegex(CloudConnectionError, "E-Mail-Adresse oder Passwort"):
                await self.module.test_connection(self.account)

    async def test_invalid_country_is_rejected_before_login(self):
        with self.assertRaisesRegex(CloudConnectionError, "zwei Buchstaben"):
            await self.module.test_connection({**self.account, "country": "Germany"})


if __name__ == "__main__":
    unittest.main()
