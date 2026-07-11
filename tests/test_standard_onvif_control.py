import unittest
from unittest.mock import patch

from app.tbc.camera_plugins.standard_onvif import control


class StandardOnvifControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.camera = {"id": 1, "host": "192.0.2.30", "username": "camera", "password": "secret", "onvif_port": 80}

    async def test_get_control_state_reports_ptz_support(self):
        with patch.object(control.onvif_control, "ptz_capability", return_value={"ptz_supported": True}) as probe:
            state = await control.get_control_state(self.camera)

        probe.assert_called_once_with(host="192.0.2.30", port=80, username="camera", password="secret")
        self.assertTrue(state["ptz_supported"])
        self.assertFalse(state["floodlight_supported"])
        self.assertFalse(state["is_battery"])

    async def test_send_control_ptz_forwards_command_to_onvif(self):
        with patch.object(control.onvif_control, "ptz_move") as move:
            result = await control.send_control(self.camera, action="ptz", command="Up")

        move.assert_called_once_with(
            host="192.0.2.30",
            port=80,
            username="camera",
            password="secret",
            command="Up",
            speed=None,
            pulse_seconds=0.5,
        )
        self.assertEqual(result, {"status": "ok", "action": "ptz"})

    async def test_send_control_rejects_unsupported_action(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="reboot")


if __name__ == "__main__":
    unittest.main()
