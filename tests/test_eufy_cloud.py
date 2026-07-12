import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from app.tbc.cloud_modules import CloudConnectionError
from app.tbc.cloud_plugins.eufy import module as eufy_plugin
from app.tbc.cloud_plugins.eufy.module import EufyCloudModule


class FakeCamera:
    def __init__(self, serial, name, model, ip_address=None):
        self.serial = serial
        self.name = name
        self.model = model
        self.ip_address = ip_address


class FakeApi:
    last_instance = None
    instances = []
    authenticate_callback = None

    def __init__(self, email, password, session, country="US"):
        type(self).last_instance = self
        type(self).instances.append(self)
        self.email = email
        self.password = password
        self._session = session
        self.country = country
        self.cameras = {
            "cam1": FakeCamera("cam1", "Eingang", "EufyCam 3", "192.168.1.25"),
            "cam2": FakeCamera("cam2", "Garten", "SoloCam S340"),
        }
        self.stations = {"station1": object()}
        self.requests = []

    async def async_authenticate(self):
        if type(self).authenticate_callback is not None:
            await type(self).authenticate_callback(self)

    async def async_update_device_info(self):
        return None

    async def request(self, method, endpoint, **kwargs):
        self.requests.append((method, endpoint, kwargs))
        return {"code": 0}


class FakeClientSession:
    last_instance = None

    def __init__(self):
        type(self).last_instance = self
        self.closed = False
        self.post_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return object()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.closed = True


class FakeHttpResponse:
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload):
        self.payload = payload
        self.status = 200

    def raise_for_status(self):
        return None

    async def json(self, *args, **kwargs):
        return self.payload


class FakeHttpRequest:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, traceback):
        return None


class FakeVerificationSession:
    def __init__(self, payload):
        self.payload = payload
        self.post_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return FakeHttpRequest(FakeHttpResponse(self.payload))


class FakeInvalidCredentialsError(Exception):
    pass


class FakeCaptchaRequiredError(Exception):
    pass


class FakeNeedVerifyCodeError(Exception):
    pass


class FakeVerifyCodeError(Exception):
    pass


class EufyCloudModuleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeApi.last_instance = None
        FakeApi.instances = []
        FakeApi.authenticate_callback = None
        with eufy_plugin._PENDING_CHALLENGES_LOCK:
            eufy_plugin._PENDING_CHALLENGES.clear()

        aiohttp_module = types.ModuleType("aiohttp")
        aiohttp_module.ClientSession = FakeClientSession
        eufy_module = types.ModuleType("eufy_security")
        eufy_module.API = FakeApi
        eufy_module.InvalidCredentialsError = FakeInvalidCredentialsError
        eufy_module.CaptchaRequiredError = FakeCaptchaRequiredError
        errors_module = types.ModuleType("eufy_security.errors")
        errors_module.NeedVerifyCodeError = FakeNeedVerifyCodeError
        errors_module.VerifyCodeError = FakeVerifyCodeError
        errors_module.VerifyCodeExpiredError = FakeVerifyCodeError
        errors_module.VerifyCodeMaxError = FakeVerifyCodeError
        errors_module.VerifyCodeNoneMatchError = FakeVerifyCodeError
        self._patcher = patch.dict(
            sys.modules,
            {
                "aiohttp": aiohttp_module,
                "eufy_security": eufy_module,
                "eufy_security.errors": errors_module,
            },
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.module = EufyCloudModule()
        self.account = {
            "id": 7,
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
        self.assertEqual(FakeApi.last_instance.country, "DE")
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
        async def failing_login(api):
            raise FakeInvalidCredentialsError("bad password")

        FakeApi.authenticate_callback = failing_login
        with self.assertRaisesRegex(CloudConnectionError, "E-Mail-Adresse oder Passwort"):
            await self.module.test_connection(self.account)

    async def test_invalid_country_is_rejected_before_login(self):
        with self.assertRaisesRegex(CloudConnectionError, "zwei Buchstaben"):
            await self.module.test_connection({**self.account, "country": "Germany"})

    async def test_verification_requirement_requests_email_code(self):
        async def needs_verification(api):
            api._session.login_response = {"data": {"auth_token": "temporary-token"}}
            api._session.api_base = "https://security-app-eu.eufylife.com"
            raise FakeNeedVerifyCodeError("need validate code")

        FakeApi.authenticate_callback = needs_verification
        send_code = AsyncMock()
        with patch.object(eufy_plugin, "_send_verification_code", send_code):
            with self.assertRaisesRegex(CloudConnectionError, "per E-Mail gesendet"):
                await self.module.test_connection(self.account)

        send_code.assert_awaited_once()
        self.assertIsNotNone(
            eufy_plugin._get_pending_challenge(
                eufy_plugin._challenge_key(self.account, "guest@example.com", "DE")
            )
        )

    async def test_verification_code_is_used_and_device_is_trusted(self):
        async def authenticate(api):
            if not api._session.verification_code:
                api._session.login_response = {
                    "data": {"auth_token": "temporary-token"}
                }
                api._session.api_base = "https://security-app-eu.eufylife.com"
                raise FakeNeedVerifyCodeError("need validate code")

        FakeApi.authenticate_callback = authenticate
        with patch.object(eufy_plugin, "_send_verification_code", AsyncMock()):
            with self.assertRaises(CloudConnectionError):
                await self.module.test_connection(self.account)

        pending_api = FakeApi.last_instance
        await self.module.test_connection(
            {**self.account, "verification_code": "123456"}
        )

        login_session = FakeApi.last_instance._session
        self.assertIs(FakeApi.last_instance, pending_api)
        self.assertEqual(login_session.verification_code, "123456")
        self.assertEqual(login_session.temporary_token, "temporary-token")
        self.assertEqual(FakeApi.last_instance.requests[0][1], "v1/app/trust_device/add")
        self.assertEqual(
            FakeApi.last_instance.requests[0][2]["json"]["verify_code"], "123456"
        )

    async def test_stale_verification_code_is_discarded_and_requests_new_code(self):
        async def needs_verification(api):
            self.assertEqual(api._session.verification_code, "")
            api._session.login_response = {"data": {"auth_token": "new-token"}}
            api._session.api_base = "https://security-app-eu.eufylife.com"
            raise FakeNeedVerifyCodeError("need validate code")

        FakeApi.authenticate_callback = needs_verification
        send_code = AsyncMock()
        with patch.object(eufy_plugin, "_send_verification_code", send_code):
            with self.assertRaisesRegex(CloudConnectionError, "per E-Mail gesendet"):
                await self.module.test_connection(
                    {**self.account, "verification_code": "stale-code"}
                )

        send_code.assert_awaited_once()

    def test_login_session_injects_verification_code_into_login_payload(self):
        raw_session = FakeClientSession()
        login_session = eufy_plugin._EufyLoginSession(
            raw_session,
            "654321",
            temporary_token="temporary-token",
        )

        login_session.post(
            "https://example.test/v2/passport/login_sec",
            json={"email": "guest@example.com"},
        )

        payload = raw_session.post_calls[0][1]["json"]
        self.assertEqual(payload["verify_code"], "654321")
        self.assertEqual(
            raw_session.post_calls[0][1]["headers"]["x-auth-token"],
            "temporary-token",
        )

    async def test_send_verification_code_uses_temporary_login_token(self):
        raw_session = FakeVerificationSession({"code": 0})
        login_session = eufy_plugin._EufyLoginSession(raw_session, "")
        login_session.api_base = "https://security-app-eu.eufylife.com"
        login_session.login_response = {"data": {"auth_token": "temporary-token"}}
        api_module = types.ModuleType("eufy_security.api")
        api_module.DEFAULT_HEADERS = {"App_version": "test"}

        with patch.dict(sys.modules, {"eufy_security.api": api_module}):
            await eufy_plugin._send_verification_code(login_session, "DE")

        url, request = raw_session.post_calls[0]
        self.assertTrue(url.endswith("/v1/sms/send/verify_code"))
        self.assertEqual(request["headers"]["x-auth-token"], "temporary-token")
        self.assertEqual(request["json"]["message_type"], 2)

    async def test_login_response_accepts_json_without_content_type_header(self):
        raw_session = FakeVerificationSession({"code": 0})
        login_session = eufy_plugin._EufyLoginSession(raw_session, "123456")
        response = FakeHttpResponse({"code": 0, "data": {"auth_token": "token"}})
        response.headers = {}
        captured = eufy_plugin._CapturedLoginResponse(response, login_session)

        self.assertEqual(captured.headers["Content-Type"], "application/json")
        payload = await captured.json()

        self.assertEqual(payload["code"], 0)
        self.assertEqual(login_session.login_response, payload)

    async def test_incomplete_login_response_has_actionable_error_and_debug_data(self):
        login_session = eufy_plugin._EufyLoginSession(
            FakeVerificationSession({}), "123456", "debug123"
        )
        response = FakeHttpResponse({"code": 0, "msg": "ok", "data": None})
        response.headers = {}
        captured = eufy_plugin._CapturedLoginResponse(response, login_session)

        with self.assertLogs("tbc.cloud.eufy", level="DEBUG") as logs:
            with self.assertRaisesRegex(CloudConnectionError, "keine Kontodaten"):
                await captured.json()

        output = "\n".join(logs.output)
        self.assertIn("debug_id=debug123", output)
        self.assertIn("content_type=<fehlt>", output)
        self.assertIn("eufy_code=0", output)
        self.assertIn("data_type=NoneType", output)


if __name__ == "__main__":
    unittest.main()
