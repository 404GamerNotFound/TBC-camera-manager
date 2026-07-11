import unittest
from unittest.mock import patch

from app.tbc.camera_plugins.aqara import control


class AqaraControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.camera = {"id": 1, "host": "192.0.2.40", "username": "camera", "password": "secret", "onvif_port": 5000}

    async def test_get_control_state_reports_ptz_support(self):
        with patch.object(control.onvif_control, "ptz_capability", return_value={"ptz_supported": False}) as probe:
            state = await control.get_control_state(self.camera)

        probe.assert_called_once_with(host="192.0.2.40", port=5000, username="camera", password="secret")
        self.assertFalse(state["ptz_supported"])
        self.assertFalse(state["pir_supported"])

    async def test_send_control_ptz_forwards_command_to_onvif(self):
        with patch.object(control.onvif_control, "ptz_move") as move:
            await control.send_control(self.camera, action="ptz", command="Down", speed=40)

        move.assert_called_once_with(
            host="192.0.2.40",
            port=5000,
            username="camera",
            password="secret",
            command="Down",
            speed=40,
            pulse_seconds=0.5,
        )

    async def test_send_control_rejects_unsupported_action(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="siren")


if __name__ == "__main__":
    unittest.main()
