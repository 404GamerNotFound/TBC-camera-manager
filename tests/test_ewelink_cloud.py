import sys
import types
import unittest
from unittest.mock import patch

from app.tbc.cloud_modules import CloudConnectionError
from app.tbc.cloud_plugins.ewelink.module import EwelinkCloudModule


class FakeDeviceExtra:
    def __init__(self, model):
        self.model = model


class FakeDevice:
    def __init__(self, deviceid, name, online, model=None, product_model=None):
        self.deviceid = deviceid
        self.name = name
        self.online = online
        self.extra = FakeDeviceExtra(model) if model else None
        self.product_model = product_model


class FakeEWeLinkError(Exception):
    def __init__(self, msg, error):
        super().__init__(msg)
        self.msg = msg
        self.error = error


class FakeEWeLink:
    instance = None
    login_error = None

    def __init__(self, app_cred, user_cred, client_session=None):
        type(self).instance = self
        self.app_cred = app_cred
        self.user_cred = user_cred
        self.logged_in = False
        self.closed = False
        self._devices = [
            FakeDevice("dev1", "Terrassenkamera", True, model="GK-200MP2-B"),
            FakeDevice("dev2", "Garage", False, product_model="MINIR4"),
        ]

    async def login(self, region="cn"):
        if type(self).login_error is not None:
            raise type(self).login_error
        self.logged_in = True
        return object()

    async def get_thing_list(self):
        return self._devices

    async def close(self):
        self.closed = True


class EwelinkCloudModuleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeEWeLink.instance = None
        FakeEWeLink.login_error = None

        ewelink_module = types.ModuleType("ewelink")
        ewelink_module.EWeLink = FakeEWeLink
        types_module = types.ModuleType("ewelink.types")

        class FakeAppCredentials:
            def __init__(self, id, secret):
                self.id = id
                self.secret = secret

        class FakeEmailUserCredentials:
            def __init__(self, email, password):
                self.email = email
                self.password = password

        types_module.AppCredentials = FakeAppCredentials
        types_module.EmailUserCredentials = FakeEmailUserCredentials
        impl_module = types.ModuleType("ewelink.ewelink")
        impl_module.EWeLinkError = FakeEWeLinkError

        self._patcher = patch.dict(
            sys.modules,
            {
                "ewelink": ewelink_module,
                "ewelink.types": types_module,
                "ewelink.ewelink": impl_module,
            },
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.module = EwelinkCloudModule()
        self.account = {
            "app_id": "app-123",
            "app_secret": "secret-456",
            "email": "guest@example.com",
            "password": "pw",
        }

    async def test_connection_reports_device_count(self):
        message = await self.module.test_connection(self.account)

        self.assertIn("2 Gerät(e)", message)
        self.assertEqual(FakeEWeLink.instance.app_cred.id, "app-123")
        self.assertTrue(FakeEWeLink.instance.closed)

    async def test_discover_devices_never_exposes_a_stream_uri(self):
        devices = await self.module.discover_devices(self.account)

        self.assertEqual(len(devices), 2)
        self.assertTrue(all(device.manual_stream_uri is None for device in devices))
        self.assertTrue(all(device.suggested_module_key == "sonoff" for device in devices))

    async def test_discover_devices_prefers_extra_model_over_product_model(self):
        devices = await self.module.discover_devices(self.account)

        by_name = {device.name: device for device in devices}
        self.assertEqual(by_name["Terrassenkamera"].model, "GK-200MP2-B")
        self.assertTrue(by_name["Terrassenkamera"].online)
        self.assertEqual(by_name["Garage"].model, "MINIR4")
        self.assertFalse(by_name["Garage"].online)

    async def test_missing_app_credentials_are_rejected_before_login(self):
        with self.assertRaisesRegex(CloudConnectionError, "App-ID und App-Secret"):
            await self.module.test_connection({**self.account, "app_id": ""})

        self.assertIsNone(FakeEWeLink.instance)

    async def test_missing_account_credentials_are_rejected_before_login(self):
        with self.assertRaisesRegex(CloudConnectionError, "E-Mail-Adresse und Passwort"):
            await self.module.test_connection({**self.account, "password": ""})

    async def test_login_failure_is_reported_with_error_code(self):
        FakeEWeLink.login_error = FakeEWeLinkError("Invalid password", 401)

        with self.assertRaisesRegex(CloudConnectionError, "Fehlercode 401"):
            await self.module.test_connection(self.account)

        self.assertTrue(FakeEWeLink.instance.closed)

    async def test_missing_library_is_reported_gracefully(self):
        with patch.dict(sys.modules, {"ewelink": None}):
            with self.assertRaisesRegex(CloudConnectionError, "nicht installiert"):
                await self.module.test_connection(self.account)


if __name__ == "__main__":
    unittest.main()
