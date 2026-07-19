import sys
import types
import unittest
from pathlib import Path
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
    def __init__(self, profiles=None):
        self._profiles = profiles or []
        self._uri_by_token = {profile.token: uri for profile, uri in self._profiles}

    def GetProfiles(self):
        return [profile for profile, _uri in self._profiles]

    def GetStreamUri(self, request):
        return types.SimpleNamespace(Uri=self._uri_by_token[request["ProfileToken"]])


class FakeEventsService:
    def GetEventProperties(self):
        return {}


def _fake_profile(token, *, source_token=None, width=None, height=None, fps=None):
    video_encoder = None
    if width is not None or height is not None or fps is not None:
        video_encoder = types.SimpleNamespace(
            Resolution=types.SimpleNamespace(Width=width, Height=height),
            RateControl=types.SimpleNamespace(FrameRateLimit=fps),
        )
    video_source = types.SimpleNamespace(SourceToken=source_token) if source_token is not None else None
    return types.SimpleNamespace(
        token=token,
        VideoEncoderConfiguration=video_encoder,
        VideoSourceConfiguration=video_source,
    )


class FakeOnvifCamera:
    kwargs = None
    media_service = FakeMediaService()

    def __init__(self, host, port, username, password, **kwargs):
        self.__class__.kwargs = kwargs

    def create_devicemgmt_service(self):
        return FakeDeviceService()

    def create_media_service(self):
        return self.__class__.media_service

    def create_events_service(self):
        return FakeEventsService()


class OnvifTests(unittest.TestCase):
    def setUp(self):
        # Tests that need specific profiles set FakeOnvifCamera.media_service
        # themselves; resetting it here keeps that independent of test order.
        FakeOnvifCamera.media_service = FakeMediaService()

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

    def test_single_lens_camera_picks_the_higher_resolution_profile(self):
        sub = _fake_profile("sub", width=640, height=360, fps=15)
        main = _fake_profile("main", width=2560, height=1440, fps=25)
        FakeOnvifCamera.media_service = FakeMediaService(
            [(sub, "rtsp://cam/sub"), (main, "rtsp://cam/main")]
        )
        fake_module = types.SimpleNamespace(ONVIFCamera=FakeOnvifCamera)

        with patch.dict(sys.modules, {"onvif": fake_module}):
            result = onvif.probe_onvif(host="192.0.2.25", port=2020, username="camera", password="secret")

        self.assertEqual(result.stream_uris, ["rtsp://cam/main"])
        self.assertEqual(len(result.stream_profiles), 1)
        self.assertEqual(result.stream_profiles[0].uri, "rtsp://cam/main")

    def test_two_lens_camera_keeps_the_best_stream_of_each_lens(self):
        lens1_sub = _fake_profile("l1-sub", source_token="lens-1", width=640, height=360, fps=15)
        lens1_main = _fake_profile("l1-main", source_token="lens-1", width=1920, height=1080, fps=25)
        lens2_sub = _fake_profile("l2-sub", source_token="lens-2", width=640, height=360, fps=15)
        lens2_main = _fake_profile("l2-main", source_token="lens-2", width=1920, height=1080, fps=25)
        FakeOnvifCamera.media_service = FakeMediaService(
            [
                (lens1_sub, "rtsp://cam/l1-sub"),
                (lens1_main, "rtsp://cam/l1-main"),
                (lens2_sub, "rtsp://cam/l2-sub"),
                (lens2_main, "rtsp://cam/l2-main"),
            ]
        )
        fake_module = types.SimpleNamespace(ONVIFCamera=FakeOnvifCamera)

        with patch.dict(sys.modules, {"onvif": fake_module}):
            result = onvif.probe_onvif(host="192.0.2.25", port=2020, username="camera", password="secret")

        self.assertEqual(result.stream_uris, ["rtsp://cam/l1-main", "rtsp://cam/l2-main"])
        self.assertEqual(len(result.stream_profiles), 2)
        self.assertEqual({p.source_token for p in result.stream_profiles}, {"lens-1", "lens-2"})

    def test_profile_missing_encoder_and_source_metadata_does_not_crash(self):
        bare = _fake_profile("bare")
        FakeOnvifCamera.media_service = FakeMediaService([(bare, "rtsp://cam/bare")])
        fake_module = types.SimpleNamespace(ONVIFCamera=FakeOnvifCamera)

        with patch.dict(sys.modules, {"onvif": fake_module}):
            result = onvif.probe_onvif(host="192.0.2.25", port=2020, username="camera", password="secret")

        self.assertTrue(result.success)
        self.assertEqual(result.stream_uris, ["rtsp://cam/bare"])
        self.assertIsNone(result.stream_profiles[0].width)
        self.assertIsNone(result.stream_profiles[0].source_token)


class OnvifPackageIsDeclaredAsADependencyTests(unittest.TestCase):
    """probe_onvif() and onvif_control.py both do a lazy `from onvif import
    ONVIFCamera` (not a top-of-file import - see onvif.py:96), so a naive
    grep for imports at the start of a line misses it entirely. That
    exact mistake once let onvif-zeep get removed from requirements.txt,
    breaking every ONVIF-based camera (including Reolink's ONVIF fallback)
    in real deployments while every test here still passed, because these
    tests correctly fake out the "onvif" module instead of importing the
    real package. Guard against it recurring."""

    def test_onvif_zeep_is_declared_in_requirements_txt(self):
        repo_root = Path(__file__).resolve().parent.parent
        for filename in ("requirements.txt", "requirements-gpu.txt"):
            content = (repo_root / filename).read_text(encoding="utf-8")
            self.assertIn("onvif-zeep", content, f"onvif-zeep missing from {filename}")


if __name__ == "__main__":
    unittest.main()
