import unittest
from unittest.mock import patch

from app.tbc.camera_plugins.foscam import control


class FoscamControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.camera = {"id": 1, "host": "192.0.2.60", "username": "camera", "password": "secret", "onvif_port": 888}

    async def test_get_control_state_reports_ptz_support(self):
        with patch.object(control.onvif_control, "ptz_capability", return_value={"ptz_supported": True}) as probe:
            state = await control.get_control_state(self.camera)

        probe.assert_called_once_with(host="192.0.2.60", port=888, username="camera", password="secret")
        self.assertTrue(state["ptz_supported"])

    async def test_send_control_ptz_forwards_command_to_onvif(self):
        with patch.object(control.onvif_control, "ptz_move") as move:
            await control.send_control(self.camera, action="ptz", command="Down")

        move.assert_called_once_with(
            host="192.0.2.60",
            port=888,
            username="camera",
            password="secret",
            command="Down",
            speed=None,
            pulse_seconds=0.5,
        )

    async def test_send_control_rejects_unsupported_action(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="reboot")


if __name__ == "__main__":
    unittest.main()
