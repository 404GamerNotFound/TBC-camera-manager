import sys
import types
import unittest
from unittest.mock import patch

from app.tbc.camera_modules import onvif_control


class FakeProfile:
    def __init__(self, token):
        self.token = token


class FakeMediaService:
    def __init__(self, profiles, analytics_configs=()):
        self._profiles = profiles
        self.analytics_configs = list(analytics_configs)
        self.set_analytics_calls: list[dict] = []

    def GetProfiles(self):
        return self._profiles

    def GetVideoAnalyticsConfigurations(self):
        return self.analytics_configs

    def SetVideoAnalyticsConfiguration(self, request):
        self.set_analytics_calls.append(request)


class FakeNamed:
    def __init__(self, token, name=None):
        self.token = token
        if name is not None:
            self.Name = name


class FakeLayout:
    def __init__(self, columns=None, rows=None):
        self.Columns = columns
        self.Rows = rows
        self.Extension = None


class FakeElementItem:
    def __init__(self, name, value):
        self.Name = name
        self._value_1 = value


class FakeAnalyticsModule:
    def __init__(self, module_type, element_items=()):
        self.Type = module_type
        self.Parameters = types.SimpleNamespace(ElementItem=list(element_items))


class FakeAnalyticsConfig:
    def __init__(self, token, modules=()):
        self.token = token
        self.AnalyticsEngineConfiguration = types.SimpleNamespace(AnalyticsModule=list(modules))


class FakePtzService:
    def __init__(
        self,
        configurations=("cfg",),
        stop_error: Exception | None = None,
        presets=(),
        tours=(),
    ):
        self.configurations = configurations
        self.stop_error = stop_error
        self.presets = presets
        self.tours = tours
        self.calls: list[tuple[str, dict]] = []

    def GetConfigurations(self):
        return self.configurations

    def ContinuousMove(self, request):
        self.calls.append(("ContinuousMove", request))

    def Stop(self, request):
        self.calls.append(("Stop", request))
        if self.stop_error:
            raise self.stop_error

    def GetPresets(self, request):
        self.calls.append(("GetPresets", request))
        return self.presets

    def GotoPreset(self, request):
        self.calls.append(("GotoPreset", request))

    def SetPreset(self, request):
        self.calls.append(("SetPreset", request))
        return "new-preset-token"

    def RemovePreset(self, request):
        self.calls.append(("RemovePreset", request))

    def GetPresetTours(self, request):
        self.calls.append(("GetPresetTours", request))
        return self.tours

    def OperatePresetTour(self, request):
        self.calls.append(("OperatePresetTour", request))


class FakeOnvifCamera:
    last_instance = None
    profiles = [FakeProfile("profile-1")]
    ptz_configurations: tuple = ("cfg",)
    stop_error: Exception | None = None
    presets: tuple = ()
    tours: tuple = ()
    analytics_configs: tuple = ()

    def __init__(self, host, port, username, password, **kwargs):
        self.host = host
        self.port = port
        self.media_service = FakeMediaService(type(self).profiles, type(self).analytics_configs)
        self.ptz_service = FakePtzService(
            type(self).ptz_configurations, type(self).stop_error, type(self).presets, type(self).tours
        )
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
        FakeOnvifCamera.presets = ()
        FakeOnvifCamera.tours = ()
        FakeOnvifCamera.analytics_configs = ()
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

    def test_ptz_presets_returns_name_to_token_mapping(self):
        FakeOnvifCamera.presets = [FakeNamed("tok-1", "Garden"), FakeNamed("tok-2")]

        result = onvif_control.ptz_presets(host="192.0.2.1", port=2020, username="u", password="p")

        self.assertEqual(result, {"Garden": "tok-1", "Preset 2": "tok-2"})

    def test_ptz_presets_returns_empty_on_failure(self):
        FakeOnvifCamera.profiles = []

        result = onvif_control.ptz_presets(host="192.0.2.1", port=2020, username="u", password="p")

        self.assertEqual(result, {})

    def test_ptz_goto_preset_sends_preset_token(self):
        onvif_control.ptz_goto_preset(
            host="192.0.2.1", port=2020, username="u", password="p", preset_token="tok-1"
        )

        calls = FakeOnvifCamera.last_instance.ptz_service.calls
        self.assertEqual(calls, [("GotoPreset", {"ProfileToken": "profile-1", "PresetToken": "tok-1"})])

    def test_ptz_save_preset_sends_preset_name(self):
        onvif_control.ptz_save_preset(host="192.0.2.1", port=2020, username="u", password="p", name="Garden")

        calls = FakeOnvifCamera.last_instance.ptz_service.calls
        self.assertEqual(calls, [("SetPreset", {"ProfileToken": "profile-1", "PresetName": "Garden"})])

    def test_ptz_remove_preset_sends_preset_token(self):
        onvif_control.ptz_remove_preset(
            host="192.0.2.1", port=2020, username="u", password="p", preset_token="tok-1"
        )

        calls = FakeOnvifCamera.last_instance.ptz_service.calls
        self.assertEqual(calls, [("RemovePreset", {"ProfileToken": "profile-1", "PresetToken": "tok-1"})])

    def test_ptz_patrol_tours_returns_supported_with_tours(self):
        FakeOnvifCamera.tours = [FakeNamed("tour-1", "Night round")]

        result = onvif_control.ptz_patrol_tours(host="192.0.2.1", port=2020, username="u", password="p")

        self.assertTrue(result["ptz_patrol_supported"])
        self.assertEqual(result["ptz_patrol_tours"], {"Night round": "tour-1"})

    def test_ptz_patrol_tours_unsupported_on_failure(self):
        FakeOnvifCamera.profiles = []

        result = onvif_control.ptz_patrol_tours(host="192.0.2.1", port=2020, username="u", password="p")

        self.assertFalse(result["ptz_patrol_supported"])
        self.assertEqual(result["ptz_patrol_tours"], {})

    def test_ptz_operate_tour_sends_operation(self):
        onvif_control.ptz_operate_tour(
            host="192.0.2.1", port=2020, username="u", password="p", tour_token="tour-1", operation="Start"
        )

        calls = FakeOnvifCamera.last_instance.ptz_service.calls
        self.assertEqual(
            calls, [("OperatePresetTour", {"ProfileToken": "profile-1", "PresetTourToken": "tour-1", "Operation": "Start"})]
        )

    def test_motion_zone_capability_reports_grid_size(self):
        layout = FakeLayout(columns=8, rows=6)
        module = FakeAnalyticsModule("tt:CellMotionDetector", [FakeElementItem("Layout", layout)])
        FakeOnvifCamera.analytics_configs = [FakeAnalyticsConfig("analytics-1", [module])]

        result = onvif_control.motion_zone_capability(host="192.0.2.1", port=2020, username="u", password="p")

        self.assertEqual(
            result,
            {
                "md_zone_supported": True,
                "md_zone_config_token": "analytics-1",
                "md_zone_columns": 8,
                "md_zone_rows": 6,
            },
        )

    def test_motion_zone_capability_falls_back_to_defaults_without_layout_size(self):
        module = FakeAnalyticsModule("tt:CellMotionDetector", [])
        FakeOnvifCamera.analytics_configs = [FakeAnalyticsConfig("analytics-1", [module])]

        result = onvif_control.motion_zone_capability(host="192.0.2.1", port=2020, username="u", password="p")

        self.assertTrue(result["md_zone_supported"])
        self.assertEqual(result["md_zone_columns"], onvif_control.DEFAULT_MOTION_ZONE_COLUMNS)
        self.assertEqual(result["md_zone_rows"], onvif_control.DEFAULT_MOTION_ZONE_ROWS)

    def test_motion_zone_capability_unsupported_without_cell_motion_module(self):
        module = FakeAnalyticsModule("tt:SomeOtherAnalytics", [])
        FakeOnvifCamera.analytics_configs = [FakeAnalyticsConfig("analytics-1", [module])]

        result = onvif_control.motion_zone_capability(host="192.0.2.1", port=2020, username="u", password="p")

        self.assertEqual(result, {"md_zone_supported": False})

    def test_motion_zone_capability_unsupported_on_failure(self):
        FakeOnvifCamera.profiles = []

        result = onvif_control.motion_zone_capability(host="192.0.2.1", port=2020, username="u", password="p")

        self.assertEqual(result, {"md_zone_supported": False})

    def test_set_motion_zone_writes_layout_and_persists(self):
        layout = FakeLayout()
        module = FakeAnalyticsModule("tt:CellMotionDetector", [FakeElementItem("Layout", layout)])
        config = FakeAnalyticsConfig("analytics-1", [module])
        FakeOnvifCamera.analytics_configs = [config]

        onvif_control.set_motion_zone(
            host="192.0.2.1",
            port=2020,
            username="u",
            password="p",
            config_token="analytics-1",
            columns=4,
            rows=3,
            cells="111000111000",
        )

        self.assertEqual(layout.Columns, 4)
        self.assertEqual(layout.Rows, 3)
        self.assertEqual(layout.Extension, "111000111000")
        set_calls = FakeOnvifCamera.last_instance.media_service.set_analytics_calls
        self.assertEqual(set_calls, [{"Configuration": config, "ForcePersistence": True}])

    def test_set_motion_zone_raises_for_unknown_config_token(self):
        FakeOnvifCamera.analytics_configs = []

        with self.assertRaises(RuntimeError):
            onvif_control.set_motion_zone(
                host="192.0.2.1",
                port=2020,
                username="u",
                password="p",
                config_token="missing",
                columns=4,
                rows=3,
                cells="1111",
            )

    def test_set_motion_zone_raises_without_cell_motion_module(self):
        config = FakeAnalyticsConfig("analytics-1", [])
        FakeOnvifCamera.analytics_configs = [config]

        with self.assertRaises(RuntimeError):
            onvif_control.set_motion_zone(
                host="192.0.2.1",
                port=2020,
                username="u",
                password="p",
                config_token="analytics-1",
                columns=4,
                rows=3,
                cells="1111",
            )

    def test_set_motion_zone_raises_without_layout_parameter(self):
        module = FakeAnalyticsModule("tt:CellMotionDetector", [])
        config = FakeAnalyticsConfig("analytics-1", [module])
        FakeOnvifCamera.analytics_configs = [config]

        with self.assertRaises(RuntimeError):
            onvif_control.set_motion_zone(
                host="192.0.2.1",
                port=2020,
                username="u",
                password="p",
                config_token="analytics-1",
                columns=4,
                rows=3,
                cells="1111",
            )


if __name__ == "__main__":
    unittest.main()
