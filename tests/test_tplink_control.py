import unittest
from unittest.mock import patch

from app.tbc.camera_plugins.tplink import control


class TpLinkControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.camera = {"id": 1, "host": "192.0.2.25", "username": "camera", "password": "secret", "onvif_port": 2020}

    async def test_get_control_state_reports_ptz_support_and_no_other_capabilities(self):
        with patch.object(control.onvif_control, "ptz_capability", return_value={"ptz_supported": True}) as probe:
            state = await control.get_control_state(self.camera)

        probe.assert_called_once_with(host="192.0.2.25", port=2020, username="camera", password="secret")
        self.assertTrue(state["ptz_supported"])
        self.assertFalse(state["floodlight_supported"])
        self.assertFalse(state["pir_supported"])
        self.assertFalse(state["reboot_supported"])
        self.assertFalse(state["siren_supported"])
        self.assertFalse(state["is_battery"])

    async def test_send_control_ptz_forwards_command_to_onvif(self):
        with patch.object(control.onvif_control, "ptz_move") as move:
            result = await control.send_control(self.camera, action="ptz", command="Left", speed=80)

        move.assert_called_once_with(
            host="192.0.2.25",
            port=2020,
            username="camera",
            password="secret",
            command="Left",
            speed=80,
            pulse_seconds=0.5,
        )
        self.assertEqual(result, {"status": "ok", "action": "ptz"})

    async def test_send_control_rejects_unsupported_action(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="floodlight", state=True)

    async def test_send_control_rejects_unknown_ptz_command(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="ptz", command="Sideways")


if __name__ == "__main__":
    unittest.main()
