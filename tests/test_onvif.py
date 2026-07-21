import asyncio
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


def _notification(topic: str, *, state: str | None = None) -> dict:
    data: dict = {}
    if state is not None:
        data = {"Data": {"SimpleItem": {"Name": "State", "Value": state}}}
    return {"Topic": {"_value_1": topic}, "Message": {"Message": data}}


class ParsePullPointNotificationTests(unittest.TestCase):
    def test_motion_true_is_decoded_as_active(self):
        result = onvif.parse_pullpoint_notification(
            _notification("tns1:VideoSource/MotionAlarm", state="true")
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].detection_key, "motion")
        self.assertTrue(result[0].active)

    def test_motion_false_is_decoded_as_inactive(self):
        result = onvif.parse_pullpoint_notification(
            _notification("tns1:VideoSource/MotionAlarm", state="false")
        )
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].active)

    def test_notification_without_a_state_field_defaults_to_active(self):
        # One-shot topics (e.g. tampering alerts) often carry no boolean state -
        # their mere presence is the signal.
        result = onvif.parse_pullpoint_notification(_notification("tns1:RuleEngine/TamperDetector/Tamper"))
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].active)

    def test_unrecognized_topic_yields_nothing(self):
        result = onvif.parse_pullpoint_notification(_notification("tns1:Something/Unrelated", state="true"))
        self.assertEqual(result, [])

    def test_malformed_message_does_not_raise(self):
        self.assertEqual(onvif.parse_pullpoint_notification(None), [])
        self.assertEqual(onvif.parse_pullpoint_notification("not a dict"), [])


class PullPointStateTrackerTests(unittest.TestCase):
    def test_active_notification_is_reported_active(self):
        tracker = onvif._PullPointStateTracker(active_timeout_seconds=60.0)
        tracker.update([onvif.OnvifEventNotification("motion", True)], now=0.0)
        self.assertEqual(tracker.active_keys(now=0.0), {"motion"})

    def test_inactive_notification_clears_the_key_immediately(self):
        tracker = onvif._PullPointStateTracker(active_timeout_seconds=60.0)
        tracker.update([onvif.OnvifEventNotification("motion", True)], now=0.0)
        tracker.update([onvif.OnvifEventNotification("motion", False)], now=1.0)
        self.assertEqual(tracker.active_keys(now=1.0), set())

    def test_active_state_decays_after_the_timeout_without_a_refresh(self):
        tracker = onvif._PullPointStateTracker(active_timeout_seconds=10.0)
        tracker.update([onvif.OnvifEventNotification("motion", True)], now=0.0)
        self.assertEqual(tracker.active_keys(now=9.0), {"motion"})
        self.assertEqual(tracker.active_keys(now=11.0), set())

    def test_independent_keys_track_separately(self):
        tracker = onvif._PullPointStateTracker(active_timeout_seconds=60.0)
        tracker.update([onvif.OnvifEventNotification("motion", True)], now=0.0)
        tracker.update([onvif.OnvifEventNotification("tamper", True)], now=5.0)
        tracker.update([onvif.OnvifEventNotification("motion", False)], now=5.0)
        self.assertEqual(tracker.active_keys(now=5.0), {"tamper"})


class FakePullPointService:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def PullMessages(self, request):
        self.calls.append(request)
        if not self._responses:
            raise asyncio.CancelledError()
        return self._responses.pop(0)


class FakeEventsServiceForUnsubscribe:
    def __init__(self):
        self.unsubscribed = False

    def Unsubscribe(self):
        self.unsubscribed = True


class FakeOnvifCameraForEvents:
    def __init__(self, pullpoint, events_service):
        self._pullpoint = pullpoint
        self.event = events_service

    def create_pullpoint_service(self):
        return self._pullpoint

    def create_events_service(self):
        return self.event


class MonitorEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_active_and_inactive_states_and_unsubscribes_on_exit(self):
        response_1 = types.SimpleNamespace(
            NotificationMessage=[_notification("tns1:VideoSource/MotionAlarm", state="true")]
        )
        response_2 = types.SimpleNamespace(
            NotificationMessage=[_notification("tns1:VideoSource/MotionAlarm", state="false")]
        )
        events_service = FakeEventsServiceForUnsubscribe()
        pullpoint = FakePullPointService([response_1, response_2])
        camera = FakeOnvifCameraForEvents(pullpoint, events_service)
        seen: list[list[dict]] = []

        fake_module = types.SimpleNamespace(ONVIFCamera=lambda *a, **k: camera)
        with patch.object(onvif, "_build_onvif_camera", return_value=camera):
            with patch.dict(sys.modules, {"onvif": fake_module}):
                with self.assertRaises(asyncio.CancelledError):
                    await onvif.monitor_events(
                        {"host": "192.0.2.9", "onvif_port": 80, "username": "u", "password": "p"},
                        seen.append,
                    )

        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], [{"key": "motion", "active": True}])
        self.assertEqual(seen[1], [{"key": "motion", "active": False}])
        self.assertTrue(events_service.unsubscribed)

    async def test_empty_pulls_do_not_invoke_the_callback(self):
        empty_response = types.SimpleNamespace(NotificationMessage=[])
        pullpoint = FakePullPointService([empty_response, empty_response])
        camera = FakeOnvifCameraForEvents(pullpoint, FakeEventsServiceForUnsubscribe())
        seen: list[list[dict]] = []

        with patch.object(onvif, "_build_onvif_camera", return_value=camera):
            with patch.dict(sys.modules, {"onvif": types.SimpleNamespace(ONVIFCamera=object)}):
                with self.assertRaises(asyncio.CancelledError):
                    await onvif.monitor_events(
                        {"host": "192.0.2.9", "onvif_port": 80, "username": "u", "password": "p"},
                        seen.append,
                    )

        self.assertEqual(seen, [])

    async def test_missing_onvif_library_raises_immediately(self):
        with patch.dict(sys.modules, {"onvif": None}):
            with self.assertRaises(RuntimeError):
                await onvif.monitor_events(
                    {"host": "192.0.2.9", "onvif_port": 80, "username": "u", "password": "p"},
                    lambda _rows: None,
                )


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
