import sys
import types
import unittest
from unittest.mock import patch

from app.tbc.camera_modules import onvif_privacy_mask


class FakeService:
    def __init__(self, namespace, xaddr):
        self.Namespace = namespace
        self.XAddr = xaddr


class FakeDeviceMgmt:
    def __init__(self, services):
        self.services = services
        self.calls: list[dict] = []

    def GetServices(self, request):
        self.calls.append(request)
        return self.services


class FakeMediaService:
    def __init__(self, profiles):
        self.profiles = profiles

    def GetProfiles(self):
        return self.profiles


class FakeProfile:
    def __init__(self, config_token):
        self.VideoSourceConfiguration = types.SimpleNamespace(token=config_token)


class FakeOnvifCamera:
    last_instance = None
    services: list = [
        FakeService("http://www.onvif.org/ver20/media/wsdl", "http://192.0.2.1/onvif/media2_service")
    ]
    profiles: list = [FakeProfile("vsc-token-1")]
    user = "u"
    passwd = "p"
    encrypt = True

    def __init__(self, host, port, username, password, **kwargs):
        self.host = host
        self.devicemgmt = FakeDeviceMgmt(type(self).services)
        self.media_service = FakeMediaService(type(self).profiles)
        self.user = type(self).user
        self.passwd = type(self).passwd
        self.encrypt = type(self).encrypt
        type(self).last_instance = self

    def create_media_service(self):
        return self.media_service


class FakeMedia2Service:
    def __init__(self, masks=(), create_token="new-mask-1"):
        self.masks = list(masks)
        self.create_token = create_token
        self.calls: list[tuple[str, dict]] = []

    def GetMasks(self, request):
        self.calls.append(("GetMasks", request))
        return self.masks

    def CreateMask(self, request):
        self.calls.append(("CreateMask", request))
        return self.create_token

    def DeleteMask(self, request):
        self.calls.append(("DeleteMask", request))


class FakeONVIFServiceFactory:
    instance: FakeMedia2Service | None = None
    last_call: dict | None = None

    def __call__(self, xaddr, user, passwd, url, encrypt=True, binding_name=""):
        type(self).last_call = {
            "xaddr": xaddr,
            "user": user,
            "passwd": passwd,
            "url": url,
            "encrypt": encrypt,
            "binding_name": binding_name,
        }
        return type(self).instance


class OnvifPrivacyMaskTests(unittest.TestCase):
    def setUp(self):
        FakeOnvifCamera.services = [
            FakeService("http://www.onvif.org/ver20/media/wsdl", "http://192.0.2.1/onvif/media2_service")
        ]
        FakeOnvifCamera.profiles = [FakeProfile("vsc-token-1")]
        FakeOnvifCamera.last_instance = None
        self.media2_factory = FakeONVIFServiceFactory()
        FakeONVIFServiceFactory.instance = FakeMedia2Service()
        fake_onvif = types.SimpleNamespace(ONVIFCamera=FakeOnvifCamera)
        fake_onvif_client = types.SimpleNamespace(ONVIFService=self.media2_factory)
        self._patcher = patch.dict(sys.modules, {"onvif": fake_onvif, "onvif.client": fake_onvif_client})
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_privacy_mask_capability_reports_supported(self):
        FakeONVIFServiceFactory.instance = FakeMedia2Service(
            masks=[
                types.SimpleNamespace(
                    token="mask-1",
                    ConfigurationToken="vsc-token-1",
                    Polygon=types.SimpleNamespace(
                        Point=[
                            types.SimpleNamespace(x=-0.5, y=-0.5),
                            types.SimpleNamespace(x=0.5, y=-0.5),
                            types.SimpleNamespace(x=0.5, y=0.5),
                        ]
                    ),
                    Type="Color",
                    Enabled=True,
                )
            ]
        )

        result = onvif_privacy_mask.privacy_mask_capability(host="192.0.2.1", port=80, username="u", password="p")

        self.assertTrue(result["privacy_mask_supported"])
        self.assertEqual(result["privacy_mask_config_token"], "vsc-token-1")
        self.assertEqual(len(result["privacy_masks"]), 1)
        mask = result["privacy_masks"][0]
        self.assertEqual(mask["token"], "mask-1")
        self.assertTrue(mask["enabled"])
        self.assertEqual(mask["type"], "Color")
        self.assertEqual(mask["points"], [{"x": -0.5, "y": -0.5}, {"x": 0.5, "y": -0.5}, {"x": 0.5, "y": 0.5}])

    def test_privacy_mask_capability_unsupported_without_media2_service(self):
        FakeOnvifCamera.services = []

        result = onvif_privacy_mask.privacy_mask_capability(host="192.0.2.1", port=80, username="u", password="p")

        self.assertEqual(result, {"privacy_mask_supported": False})

    def test_privacy_mask_capability_unsupported_without_profile(self):
        FakeOnvifCamera.profiles = []

        result = onvif_privacy_mask.privacy_mask_capability(host="192.0.2.1", port=80, username="u", password="p")

        self.assertEqual(result, {"privacy_mask_supported": False})

    def test_privacy_mask_capability_unsupported_on_failure(self):
        class FailingCamera:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("connection refused")

        with patch.dict(sys.modules, {"onvif": types.SimpleNamespace(ONVIFCamera=FailingCamera)}):
            result = onvif_privacy_mask.privacy_mask_capability(host="192.0.2.1", port=80, username="u", password="p")

        self.assertEqual(result, {"privacy_mask_supported": False})

    def test_create_privacy_mask_sends_polygon_and_returns_token(self):
        token = onvif_privacy_mask.create_privacy_mask(
            host="192.0.2.1",
            port=80,
            username="u",
            password="p",
            config_token="vsc-token-1",
            points=[{"x": -0.5, "y": -0.5}, {"x": 0.5, "y": -0.5}, {"x": 0.5, "y": 0.5}],
        )

        self.assertEqual(token, "new-mask-1")
        calls = FakeONVIFServiceFactory.instance.calls
        self.assertEqual(calls[0][0], "CreateMask")
        mask = calls[0][1]["Mask"]
        self.assertEqual(mask["ConfigurationToken"], "vsc-token-1")
        self.assertEqual(mask["Type"], "Color")
        self.assertEqual(len(mask["Polygon"]["Point"]), 3)

    def test_create_privacy_mask_requires_at_least_three_points(self):
        with self.assertRaises(ValueError):
            onvif_privacy_mask.create_privacy_mask(
                host="192.0.2.1", port=80, username="u", password="p",
                config_token="vsc-token-1", points=[{"x": 0.0, "y": 0.0}],
            )

    def test_create_privacy_mask_raises_without_media2_support(self):
        FakeOnvifCamera.services = []

        with self.assertRaises(RuntimeError):
            onvif_privacy_mask.create_privacy_mask(
                host="192.0.2.1", port=80, username="u", password="p",
                config_token="vsc-token-1",
                points=[{"x": -0.5, "y": -0.5}, {"x": 0.5, "y": -0.5}, {"x": 0.5, "y": 0.5}],
            )

    def test_delete_privacy_mask_sends_token(self):
        onvif_privacy_mask.delete_privacy_mask(host="192.0.2.1", port=80, username="u", password="p", token="mask-1")

        calls = FakeONVIFServiceFactory.instance.calls
        self.assertEqual(calls, [("DeleteMask", {"Token": "mask-1"})])

    def test_media2_service_uses_bundled_wsdl_and_credentials(self):
        onvif_privacy_mask.delete_privacy_mask(host="192.0.2.1", port=80, username="u", password="p", token="mask-1")

        call = FakeONVIFServiceFactory.last_call
        self.assertEqual(call["xaddr"], "http://192.0.2.1/onvif/media2_service")
        self.assertEqual(call["user"], "u")
        self.assertEqual(call["passwd"], "p")
        self.assertTrue(call["url"].endswith("onvif_media2_schema/onvif_media2.wsdl"))
        self.assertEqual(call["binding_name"], "{http://www.onvif.org/ver20/media/wsdl}Media2Binding")


class MaskSummaryFallbackTests(unittest.TestCase):
    def test_mask_summary_uses_clean_named_fields_when_present(self):
        mask = types.SimpleNamespace(
            token="mask-1",
            Polygon=types.SimpleNamespace(Point=[types.SimpleNamespace(x=0.1, y=0.2)]),
            Type="Color",
            Enabled=False,
        )

        summary = onvif_privacy_mask._mask_summary(mask)

        self.assertEqual(summary, {"token": "mask-1", "enabled": False, "type": "Color", "points": [{"x": 0.1, "y": 0.2}]})

    def test_mask_summary_falls_back_to_value_1_sequence(self):
        type_element = types.SimpleNamespace(tag="{http://www.onvif.org/ver10/schema}Type", text="Color")
        enabled_element = types.SimpleNamespace(tag="{http://www.onvif.org/ver10/schema}Enabled", text="true")
        mask = types.SimpleNamespace(
            token="mask-2",
            Polygon=None,
            Type=None,
            Enabled=None,
            _value_1=[{"Point": [{"x": -1.0, "y": -1.0}, {"x": 1.0, "y": -1.0}, {"x": 1.0, "y": 1.0}]}, type_element, enabled_element],
        )

        summary = onvif_privacy_mask._mask_summary(mask)

        self.assertEqual(summary["type"], "Color")
        self.assertTrue(summary["enabled"])
        self.assertEqual(len(summary["points"]), 3)


class Media2AsyncWrapperTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.camera = {"id": 1, "host": "192.0.2.30", "username": "camera", "password": "secret", "onvif_port": 80}

    async def test_get_privacy_mask_control_state_calls_capability_probe(self):
        with patch.object(
            onvif_privacy_mask, "privacy_mask_capability", return_value={"privacy_mask_supported": True}
        ) as probe:
            state = await onvif_privacy_mask.get_privacy_mask_control_state(self.camera)

        probe.assert_called_once_with(host="192.0.2.30", port=80, username="camera", password="secret")
        self.assertTrue(state["privacy_mask_supported"])

    async def test_send_control_create_forwards_points(self):
        with patch.object(onvif_privacy_mask, "create_privacy_mask", return_value="mask-9") as create:
            result = await onvif_privacy_mask.send_privacy_mask_control(
                self.camera,
                action="privacy_mask_create",
                config_token="vsc-1",
                points=[{"x": -0.5, "y": -0.5}, {"x": 0.5, "y": -0.5}, {"x": 0.5, "y": 0.5}],
            )

        create.assert_called_once_with(
            host="192.0.2.30",
            port=80,
            username="camera",
            password="secret",
            config_token="vsc-1",
            points=[{"x": -0.5, "y": -0.5}, {"x": 0.5, "y": -0.5}, {"x": 0.5, "y": 0.5}],
        )
        self.assertEqual(result, {"status": "ok", "action": "privacy_mask_create", "token": "mask-9"})

    async def test_send_control_create_requires_three_points(self):
        with self.assertRaises(ValueError):
            await onvif_privacy_mask.send_privacy_mask_control(
                self.camera, action="privacy_mask_create", config_token="vsc-1", points=[{"x": 0, "y": 0}]
            )

    async def test_send_control_delete_forwards_token(self):
        with patch.object(onvif_privacy_mask, "delete_privacy_mask") as delete:
            result = await onvif_privacy_mask.send_privacy_mask_control(
                self.camera, action="privacy_mask_delete", token="mask-9"
            )

        delete.assert_called_once_with(host="192.0.2.30", port=80, username="camera", password="secret", token="mask-9")
        self.assertEqual(result, {"status": "ok", "action": "privacy_mask_delete"})

    async def test_send_control_rejects_unsupported_action(self):
        with self.assertRaises(ValueError):
            await onvif_privacy_mask.send_privacy_mask_control(self.camera, action="reboot")


class BundledWsdlOfflineParseTests(unittest.TestCase):
    """Guards against silent corruption of the bundled Media2 WSDL/schema closure.

    onvif_media2_schema/ was hand-assembled from the ONVIF Foundation's own
    published media2.wsdl and onvif.xsd (which do not fully agree with each
    other - see onvif_privacy_mask.py's module docstring) plus several W3C/
    OASIS schema files, specifically so the whole thing parses and builds SOAP
    requests without any network access. This test exercises that directly.
    """

    def test_bundled_wsdl_parses_offline_and_builds_create_mask_request(self):
        try:
            from zeep import Client
            from zeep.transports import Transport
        except ImportError:
            self.skipTest("zeep is not installed")

        class BlockingTransport(Transport):
            def load(self, url):
                if url.startswith("http://") or url.startswith("https://"):
                    raise AssertionError(f"bundled WSDL required a network fetch: {url}")
                return super().load(url)

        client = Client(wsdl=onvif_privacy_mask._WSDL_PATH, transport=BlockingTransport())
        service = client.create_service(onvif_privacy_mask.MEDIA2_BINDING, "http://192.0.2.1/onvif/media2_service")

        captured = {}

        def fake_post(self, address, message, headers):
            captured["message"] = message

            class FakeResponse:
                status_code = 200
                headers: dict = {}
                content = (
                    b'<?xml version="1.0"?><soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
                    b'<soap:Body><tr2:CreateMaskResponse xmlns:tr2="http://www.onvif.org/ver20/media/wsdl">'
                    b"<tr2:Token>mask-1</tr2:Token></tr2:CreateMaskResponse></soap:Body></soap:Envelope>"
                )

            return FakeResponse()

        client.transport.post = types.MethodType(fake_post, client.transport)
        result = service.CreateMask(
            Mask={
                "ConfigurationToken": "vsc-token-1",
                "Polygon": {"Point": [{"x": -0.5, "y": -0.5}, {"x": 0.5, "y": -0.5}, {"x": 0.5, "y": 0.5}]},
                "Type": "Color",
                "Color": onvif_privacy_mask.DEFAULT_MASK_COLOR,
                "Enabled": True,
            }
        )
        self.assertEqual(result, "mask-1")
        self.assertIn(b"CreateMask", captured["message"])


if __name__ == "__main__":
    unittest.main()
