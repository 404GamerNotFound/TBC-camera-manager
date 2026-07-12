import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.tbc.camera_plugins.reolink import control


class FakeControlHost:
    instance = None

    def __init__(self, *args, **kwargs):
        type(self).instance = self
        self.channels = [0]
        self.closed = False
        self.ptz_calls = []
        self.whiteled_calls = []
        self.pir_calls = []
        self.siren_calls = []
        self.rebooted_channel = "unset"
        self._supported = {
            ("ptz", 0): True,
            ("floodLight", 0): True,
            ("PIR", 0): True,
            ("reboot", None): True,
            ("siren_play", 0): True,
            ("battery", 0): True,
            ("firmware", 0): True,
            ("zoom", 0): True,
            ("focus", 0): True,
            ("play_quick_reply", 0): True,
        }
        self._floodlight_state = True
        self._pir_enabled = False
        self._battery_percentage = 77
        self._battery_temperature = 21
        self._battery_status = 1
        self._ptz_presets_data = {0: {"Eingang": 1, "Garten": 2}}
        self._sw_version = "v3.1.0.100_old"
        self._new_firmware = False
        self._sw_upload_progress: dict = {}
        self.check_new_firmware_calls = []
        self.update_firmware_calls = []
        self._zoom_position = 10
        self._focus_position = 20
        self._zoom_range_data = {0: {"zoom": {"min": 0, "max": 100}, "focus": {"min": 0, "max": 50}}}
        self._is_doorbell = False
        self._quick_reply_options = {-1: "Aus", 1: "Hallo, ich bin gleich da", 2: "Bitte Paket abstellen"}
        self.zoom_calls = []
        self.focus_calls = []
        self.quick_reply_calls = []

    async def get_host_data(self):
        return None

    async def get_states(self):
        return None

    def ptz_presets(self, channel):
        return self._ptz_presets_data.get(channel, {})

    def camera_sw_version(self, channel):
        return self._sw_version

    async def check_new_firmware(self, ch_list=None):
        self.check_new_firmware_calls.append(ch_list)

    def firmware_update_available(self, channel=None):
        return self._new_firmware

    async def update_firmware(self, channel=None):
        self.update_firmware_calls.append(channel)
        self._sw_upload_progress[channel] = 100

    def supported(self, channel, capability):
        return self._supported.get((capability, channel), False)

    def whiteled_state(self, channel):
        return self._floodlight_state

    def pir_enabled(self, channel):
        return self._pir_enabled

    def battery_percentage(self, channel):
        return self._battery_percentage

    def battery_temperature(self, channel):
        return self._battery_temperature

    def battery_status(self, channel):
        return self._battery_status

    async def set_ptz_command(self, channel, **kwargs):
        self.ptz_calls.append((channel, kwargs))

    async def set_whiteled(self, channel, state=None, **kwargs):
        self.whiteled_calls.append((channel, state))

    async def set_pir(self, channel, enable=None, **kwargs):
        self.pir_calls.append((channel, enable))

    async def reboot(self, channel=None):
        self.rebooted_channel = channel

    async def set_siren(self, channel, enable=True, duration=2):
        self.siren_calls.append((channel, enable, duration))

    async def logout(self):
        self.closed = True

    def get_zoom(self, channel):
        return self._zoom_position

    def get_focus(self, channel):
        return self._focus_position

    def zoom_range(self, channel):
        return self._zoom_range_data.get(channel, {})

    async def set_zoom(self, channel, position):
        self.zoom_calls.append((channel, position))

    async def set_focus(self, channel, position):
        self.focus_calls.append((channel, position))

    def is_doorbell(self, channel):
        return self._is_doorbell

    def quick_reply_dict(self, channel):
        return self._quick_reply_options

    async def play_quick_reply(self, channel, file_id):
        self.quick_reply_calls.append((channel, file_id))


class FakeNvrChannelHost(FakeControlHost):
    """A device whose only real channel is not 0 (e.g. behind an NVR)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channels = [3]
        self._supported = {
            ("ptz", 3): True,
            ("floodLight", 3): True,
        }


class ReolinkControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.camera = {"id": 1, "host": "camera", "username": "u", "password": "p", "http_port": 80}
        api_module = types.ModuleType("reolink_aio.api")
        api_module.Host = FakeControlHost
        package = types.ModuleType("reolink_aio")
        self._patcher = patch.dict(sys.modules, {"reolink_aio": package, "reolink_aio.api": api_module})
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    async def test_get_control_state_reports_capabilities_and_values(self):
        state = await control.get_control_state(self.camera)

        self.assertTrue(state["ptz_supported"])
        self.assertTrue(state["floodlight_supported"])
        self.assertTrue(state["floodlight_state"])
        self.assertTrue(state["pir_supported"])
        self.assertFalse(state["pir_enabled"])
        self.assertTrue(state["reboot_supported"])
        self.assertTrue(state["siren_supported"])
        self.assertTrue(state["is_battery"])
        self.assertEqual(state["battery_percentage"], 77)
        self.assertEqual(state["battery_status"], "charging")
        self.assertTrue(FakeControlHost.instance.closed)

    async def test_get_control_state_reports_ptz_presets(self):
        state = await control.get_control_state(self.camera)

        self.assertEqual(state["ptz_presets"], {"Eingang": 1, "Garten": 2})

    async def test_get_control_state_reports_firmware_info(self):
        state = await control.get_control_state(self.camera)

        self.assertTrue(state["firmware_supported"])
        self.assertEqual(state["firmware_current"], "v3.1.0.100_old")

    async def test_send_control_floodlight_toggles_state(self):
        await control.send_control(self.camera, action="floodlight", state=True)

        self.assertEqual(FakeControlHost.instance.whiteled_calls, [(0, True)])

    async def test_send_control_pir_toggles_state(self):
        await control.send_control(self.camera, action="pir", enable=True)

        self.assertEqual(FakeControlHost.instance.pir_calls, [(0, True)])

    async def test_send_control_reboot(self):
        await control.send_control(self.camera, action="reboot")

        self.assertEqual(FakeControlHost.instance.rebooted_channel, 0)

    async def test_send_control_siren_clamps_duration(self):
        await control.send_control(self.camera, action="siren", duration=999)

        self.assertEqual(FakeControlHost.instance.siren_calls, [(0, True, 30)])

    async def test_send_control_ptz_pulses_then_stops(self):
        await control.send_control(self.camera, action="ptz", command="Left", pulse_seconds=0.01)

        calls = FakeControlHost.instance.ptz_calls
        self.assertEqual(calls[0], (0, {"command": "Left"}))
        self.assertEqual(calls[1], (0, {"command": "Stop"}))

    async def test_send_control_ptz_stop_does_not_pulse_again(self):
        await control.send_control(self.camera, action="ptz", command="Stop")

        self.assertEqual(FakeControlHost.instance.ptz_calls, [(0, {"command": "Stop"})])

    async def test_send_control_ptz_rejects_unknown_command(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="ptz", command="Sideways")

    async def test_send_control_ptz_preset_moves_to_preset_without_pulsing(self):
        await control.send_control(self.camera, action="ptz", preset=2)

        self.assertEqual(FakeControlHost.instance.ptz_calls, [(0, {"preset": 2})])

    async def test_send_control_ptz_preset_rejects_non_numeric_id(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="ptz", preset="not-a-number")

    async def test_send_control_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="levitate")

    async def test_check_firmware_reports_up_to_date(self):
        FakeControlHost.instance = None
        result = await control.check_firmware(self.camera)

        self.assertEqual(result["current"], "v3.1.0.100_old")
        self.assertEqual(result["latest"], "v3.1.0.100_old")
        self.assertFalse(result["update_available"])
        self.assertEqual(FakeControlHost.instance.check_new_firmware_calls, [[0]])

    async def test_check_firmware_reports_update_available(self):
        # The fake Host is constructed fresh inside check_firmware(), so seed
        # its "new firmware" response through a subclass instead of mutating
        # an instance that does not exist yet.
        available = SimpleNamespace(version_string="v3.2.0.200_new", release_notes="Bugfixes")

        class HostWithUpdate(FakeControlHost):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._new_firmware = available

        with patch.object(sys.modules["reolink_aio.api"], "Host", HostWithUpdate):
            result = await control.check_firmware(self.camera)

        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest"], "v3.2.0.200_new")
        self.assertEqual(result["release_notes"], "Bugfixes")

    async def test_run_firmware_update_calls_update_and_reports_completion(self):
        available = SimpleNamespace(version_string="v3.2.0.200_new", release_notes="")

        class HostWithUpdate(FakeControlHost):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._new_firmware = available

        progress_values = []
        with patch.object(sys.modules["reolink_aio.api"], "Host", HostWithUpdate):
            await control.run_firmware_update(self.camera, progress_callback=progress_values.append)
            instance = HostWithUpdate.instance

        self.assertEqual(instance.update_firmware_calls, [0])
        self.assertIn(100, progress_values)
        self.assertTrue(instance.closed)

    async def test_run_firmware_update_without_prior_check_raises(self):
        with self.assertRaises(RuntimeError):
            await control.run_firmware_update(self.camera)

    async def test_send_control_closes_host_even_on_failure(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="unknown-action")

        self.assertTrue(FakeControlHost.instance.closed)

    async def test_get_control_state_reports_zoom_and_focus(self):
        state = await control.get_control_state(self.camera)

        self.assertTrue(state["zoom_supported"])
        self.assertEqual(state["zoom_position"], 10)
        self.assertEqual(state["zoom_range"], {"min": 0, "max": 100})
        self.assertTrue(state["focus_supported"])
        self.assertEqual(state["focus_position"], 20)
        self.assertEqual(state["focus_range"], {"min": 0, "max": 50})

    async def test_get_control_state_reports_quick_reply_options_excluding_off_sentinel(self):
        FakeControlHost.instance = None

        class DoorbellHost(FakeControlHost):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._is_doorbell = True

        with patch.object(sys.modules["reolink_aio.api"], "Host", DoorbellHost):
            state = await control.get_control_state(self.camera)

        self.assertTrue(state["is_doorbell"])
        self.assertTrue(state["quick_reply_supported"])
        self.assertEqual(
            state["quick_reply_options"],
            {"1": "Hallo, ich bin gleich da", "2": "Bitte Paket abstellen"},
        )

    async def test_send_control_zoom_sets_position(self):
        await control.send_control(self.camera, action="zoom", position=42)

        self.assertEqual(FakeControlHost.instance.zoom_calls, [(0, 42)])

    async def test_send_control_zoom_rejects_non_numeric_position(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="zoom", position="far")

    async def test_send_control_focus_sets_position(self):
        await control.send_control(self.camera, action="focus", position=15)

        self.assertEqual(FakeControlHost.instance.focus_calls, [(0, 15)])

    async def test_send_control_quick_reply_plays_file(self):
        await control.send_control(self.camera, action="quick_reply", file_id=2)

        self.assertEqual(FakeControlHost.instance.quick_reply_calls, [(0, 2)])

    async def test_send_control_quick_reply_rejects_non_numeric_file_id(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="quick_reply", file_id="clip.mp3")


class ReolinkControlNvrChannelTests(unittest.IsolatedAsyncioTestCase):
    """A camera connected behind an NVR does not necessarily report channel 0."""

    def setUp(self):
        self.camera = {"id": 1, "host": "nvr", "username": "u", "password": "p", "http_port": 80}
        api_module = types.ModuleType("reolink_aio.api")
        api_module.Host = FakeNvrChannelHost
        package = types.ModuleType("reolink_aio")
        self._patcher = patch.dict(sys.modules, {"reolink_aio": package, "reolink_aio.api": api_module})
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    async def test_get_control_state_resolves_to_the_devices_actual_channel(self):
        state = await control.get_control_state(self.camera, channel=0)

        self.assertEqual(state["channel"], 3)
        self.assertTrue(state["ptz_supported"])
        self.assertTrue(state["floodlight_supported"])

    async def test_send_control_targets_the_devices_actual_channel(self):
        await control.send_control(self.camera, action="floodlight", channel=0, state=True)

        self.assertEqual(FakeNvrChannelHost.instance.whiteled_calls, [(3, True)])


if __name__ == "__main__":
    unittest.main()
