import sys
import types
import unittest
from unittest.mock import patch

from app.tbc.camera_modules import onvif_control


class FakeProfile:
    def __init__(self, token):
        self.token = token


class FakeMediaService:
    def __init__(self, profiles):
        self._profiles = profiles

    def GetProfiles(self):
        return self._profiles


class FakePtzService:
    def __init__(self, configurations=("cfg",), stop_error: Exception | None = None):
        self.configurations = configurations
        self.stop_error = stop_error
        self.calls: list[tuple[str, dict]] = []

    def GetConfigurations(self):
        return self.configurations

    def ContinuousMove(self, request):
        self.calls.append(("ContinuousMove", request))

    def Stop(self, request):
        self.calls.append(("Stop", request))
        if self.stop_error:
            raise self.stop_error


class FakeOnvifCamera:
    last_instance = None
    profiles = [FakeProfile("profile-1")]
    ptz_configurations: tuple = ("cfg",)
    stop_error: Exception | None = None

    def __init__(self, host, port, username, password, **kwargs):
        self.host = host
        self.port = port
        self.media_service = FakeMediaService(type(self).profiles)
        self.ptz_service = FakePtzService(type(self).ptz_configurations, type(self).stop_error)
        type(self).last_instance = self

    def create_media_service(self):
        return self.media_service

    def create_ptz_service(self):
        return self.ptz_service


class FailingOnvifCamera:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("connection refused")


class OnvifControlTests(unittest.TestCase):
    def setUp(self):
        FakeOnvifCamera.profiles = [FakeProfile("profile-1")]
        FakeOnvifCamera.ptz_configurations = ("cfg",)
        FakeOnvifCamera.stop_error = None
        FakeOnvifCamera.last_instance = None
        fake_module = types.SimpleNamespace(ONVIFCamera=FakeOnvifCamera)
        self._patcher = patch.dict(sys.modules, {"onvif": fake_module})
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_ptz_capability_true_when_configurations_present(self):
        result = onvif_control.ptz_capability(host="192.0.2.1", port=2020, username="u", password="p")

        self.assertTrue(result["ptz_supported"])

    def test_ptz_capability_false_without_media_profile(self):
        FakeOnvifCamera.profiles = []

        result = onvif_control.ptz_capability(host="192.0.2.1", port=2020, username="u", password="p")

        self.assertFalse(result["ptz_supported"])

    def test_ptz_capability_false_on_connection_error(self):
        with patch.dict(sys.modules, {"onvif": types.SimpleNamespace(ONVIFCamera=FailingOnvifCamera)}):
            result = onvif_control.ptz_capability(host="192.0.2.1", port=2020, username="u", password="p")

        self.assertFalse(result["ptz_supported"])

    def test_ptz_move_sends_pan_tilt_velocity_and_pulses_stop(self):
        onvif_control.ptz_move(
            host="192.0.2.1",
            port=2020,
            username="u",
            password="p",
            command="Left",
            speed=100,
            pulse_seconds=0.01,
        )

        calls = FakeOnvifCamera.last_instance.ptz_service.calls
        self.assertEqual(calls[0][0], "ContinuousMove")
        self.assertEqual(calls[0][1]["Velocity"]["PanTilt"], {"x": -1.0, "y": 0.0})
        self.assertEqual(calls[1], ("Stop", {"ProfileToken": "profile-1"}))

    def test_ptz_move_stop_command_only_stops(self):
        onvif_control.ptz_move(host="192.0.2.1", port=2020, username="u", password="p", command="Stop")

        self.assertEqual(FakeOnvifCamera.last_instance.ptz_service.calls, [("Stop", {"ProfileToken": "profile-1"})])

    def test_ptz_move_zoom_uses_zoom_velocity(self):
        onvif_control.ptz_move(
            host="192.0.2.1", port=2020, username="u", password="p", command="ZoomInc", speed=100, pulse_seconds=0.01
        )

        calls = FakeOnvifCamera.last_instance.ptz_service.calls
        self.assertEqual(calls[0][1]["Velocity"], {"Zoom": {"x": 1.0}})

    def test_ptz_move_rejects_unknown_command(self):
        with self.assertRaises(ValueError):
            onvif_control.ptz_move(host="192.0.2.1", port=2020, username="u", password="p", command="Sideways")

    def test_ptz_move_without_profile_raises(self):
        FakeOnvifCamera.profiles = []

        with self.assertRaises(RuntimeError):
            onvif_control.ptz_move(host="192.0.2.1", port=2020, username="u", password="p", command="Up")

    def test_ptz_move_stop_pulse_failure_is_swallowed(self):
        FakeOnvifCamera.stop_error = RuntimeError("stop failed")

        onvif_control.ptz_move(
            host="192.0.2.1", port=2020, username="u", password="p", command="Up", pulse_seconds=0.01
        )

        self.assertEqual(len(FakeOnvifCamera.last_instance.ptz_service.calls), 2)


if __name__ == "__main__":
    unittest.main()
