import sys
import types
import unittest
from unittest.mock import patch

from app.tbc.reolink import control


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
        }
        self._floodlight_state = True
        self._pir_enabled = False
        self._battery_percentage = 77
        self._battery_temperature = 21
        self._battery_status = 1

    async def get_host_data(self):
        return None

    async def get_states(self):
        return None

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

    async def test_send_control_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="levitate")

    async def test_send_control_closes_host_even_on_failure(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="unknown-action")

        self.assertTrue(FakeControlHost.instance.closed)


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
