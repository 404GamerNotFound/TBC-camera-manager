import sys
import types
import unittest
from unittest.mock import patch

from app.tbc.camera_modules import onvif


class FakeDeviceService:
    def GetDeviceInformation(self):
        return {
            "Manufacturer": "TP-Link",
            "Model": "Tapo C210",
            "FirmwareVersion": "1.4.0",
            "SerialNumber": "test",
        }


class FakeMediaService:
    def GetProfiles(self):
        return []


class FakeEventsService:
    def GetEventProperties(self):
        return {}


class FakeOnvifCamera:
    kwargs = None

    def __init__(self, host, port, username, password, **kwargs):
        self.__class__.kwargs = kwargs

    def create_devicemgmt_service(self):
        return FakeDeviceService()

    def create_media_service(self):
        return FakeMediaService()

    def create_events_service(self):
        return FakeEventsService()


class OnvifTests(unittest.TestCase):
    def test_probe_uses_digest_authentication_and_camera_time_adjustment(self):
        fake_module = types.SimpleNamespace(ONVIFCamera=FakeOnvifCamera)

        with patch.dict(sys.modules, {"onvif": fake_module}):
            result = onvif.probe_onvif(
                host="192.0.2.25",
                port=2020,
                username="camera",
                password="secret",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.model, "Tapo C210")
        self.assertTrue(FakeOnvifCamera.kwargs["encrypt"])
        self.assertTrue(FakeOnvifCamera.kwargs["adjust_time"])
        self.assertFalse(FakeOnvifCamera.kwargs["event_pullpoint"])
        self.assertTrue(FakeOnvifCamera.kwargs["override_camera_address"])

    def test_authority_failure_is_reported_in_plain_language(self):
        self.assertIn(
            "ONVIF sign-in rejected",
            onvif._friendly_error(RuntimeError("Unknown error: Authority failure")),
        )


if __name__ == "__main__":
    unittest.main()
