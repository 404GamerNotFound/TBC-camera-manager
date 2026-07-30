import unittest
from unittest.mock import patch

from app.tbc.camera_plugins.standard_onvif import control


class StandardOnvifControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.camera = {"id": 1, "host": "192.0.2.30", "username": "camera", "password": "secret", "onvif_port": 80}

    async def test_get_control_state_reports_ptz_support(self):
        with patch.object(control.onvif_control, "ptz_capability", return_value={"ptz_supported": True}) as probe, \
            patch.object(control.onvif_control, "ptz_presets", return_value={"Garden": "tok-1"}), \
            patch.object(
                control.onvif_control,
                "ptz_patrol_tours",
                return_value={"ptz_patrol_supported": True, "ptz_patrol_tours": {"Night": "tour-1"}},
            ):
            state = await control.get_control_state(self.camera)

        probe.assert_called_once_with(host="192.0.2.30", port=80, username="camera", password="secret")
        self.assertTrue(state["ptz_supported"])
        self.assertEqual(state["ptz_presets"], {"Garden": "tok-1"})
        self.assertTrue(state["ptz_patrol_supported"])
        self.assertEqual(state["ptz_patrol_tours"], {"Night": "tour-1"})
        self.assertFalse(state["floodlight_supported"])
        self.assertFalse(state["is_battery"])

    async def test_get_control_state_skips_preset_probe_without_ptz(self):
        with patch.object(control.onvif_control, "ptz_capability", return_value={"ptz_supported": False}), \
            patch.object(control.onvif_control, "ptz_presets") as presets, \
            patch.object(control.onvif_control, "ptz_patrol_tours") as tours:
            state = await control.get_control_state(self.camera)

        presets.assert_not_called()
        tours.assert_not_called()
        self.assertEqual(state["ptz_presets"], {})
        self.assertFalse(state["ptz_patrol_supported"])

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

    async def test_send_control_ptz_with_preset_goes_to_preset_instead_of_command(self):
        with patch.object(control.onvif_control, "ptz_goto_preset") as goto, patch.object(
            control.onvif_control, "ptz_move"
        ) as move:
            result = await control.send_control(self.camera, action="ptz", preset="tok-1")

        goto.assert_called_once_with(
            host="192.0.2.30", port=80, username="camera", password="secret", preset_token="tok-1", speed=None
        )
        move.assert_not_called()
        self.assertEqual(result, {"status": "ok", "action": "ptz"})

    async def test_send_control_ptz_preset_save(self):
        with patch.object(control.onvif_control, "ptz_save_preset") as save:
            result = await control.send_control(self.camera, action="ptz_preset_save", name="Garden")

        save.assert_called_once_with(host="192.0.2.30", port=80, username="camera", password="secret", name="Garden")
        self.assertEqual(result, {"status": "ok", "action": "ptz_preset_save"})

    async def test_send_control_ptz_preset_save_requires_name(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="ptz_preset_save", name="  ")

    async def test_send_control_ptz_preset_delete(self):
        with patch.object(control.onvif_control, "ptz_remove_preset") as remove:
            result = await control.send_control(self.camera, action="ptz_preset_delete", preset="tok-1")

        remove.assert_called_once_with(
            host="192.0.2.30", port=80, username="camera", password="secret", preset_token="tok-1"
        )
        self.assertEqual(result, {"status": "ok", "action": "ptz_preset_delete"})

    async def test_send_control_ptz_patrol_start_and_stop(self):
        with patch.object(control.onvif_control, "ptz_operate_tour") as operate:
            result = await control.send_control(self.camera, action="ptz_patrol", tour="tour-1", command="start")

        operate.assert_called_once_with(
            host="192.0.2.30", port=80, username="camera", password="secret", tour_token="tour-1", operation="Start"
        )
        self.assertEqual(result, {"status": "ok", "action": "ptz_patrol"})

    async def test_send_control_ptz_patrol_requires_valid_command(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="ptz_patrol", tour="tour-1", command="pause")

    async def test_send_control_rejects_unsupported_action(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="reboot")

    async def test_get_control_state_merges_motion_zone_capability(self):
        with patch.object(control.onvif_control, "ptz_capability", return_value={"ptz_supported": False}), \
            patch.object(
                control.onvif_control,
                "motion_zone_capability",
                return_value={
                    "md_zone_supported": True,
                    "md_zone_config_token": "analytics-1",
                    "md_zone_columns": 8,
                    "md_zone_rows": 6,
                },
            ):
            state = await control.get_control_state(self.camera)

        self.assertTrue(state["md_zone_supported"])
        self.assertEqual(state["md_zone_config_token"], "analytics-1")
        self.assertEqual(state["md_zone_columns"], 8)
        self.assertEqual(state["md_zone_rows"], 6)

    async def test_send_control_md_zone_forwards_to_onvif(self):
        with patch.object(control.onvif_control, "set_motion_zone") as set_zone:
            result = await control.send_control(
                self.camera, action="md_zone", config_token="analytics-1", columns=4, rows=3, cells="111000111000"
            )

        set_zone.assert_called_once_with(
            host="192.0.2.30",
            port=80,
            username="camera",
            password="secret",
            config_token="analytics-1",
            columns=4,
            rows=3,
            cells="111000111000",
        )
        self.assertEqual(result, {"status": "ok", "action": "md_zone"})

    async def test_send_control_md_zone_requires_config_and_cells(self):
        with self.assertRaises(ValueError):
            await control.send_control(self.camera, action="md_zone", config_token="", columns=4, rows=3, cells="")

    async def test_get_control_state_merges_imaging_capability(self):
        with patch.object(control.onvif_control, "ptz_capability", return_value={"ptz_supported": False}), \
            patch.object(
                control.onvif_control,
                "imaging_capability",
                return_value={"image_bright_supported": True, "image_brightness": 128},
            ):
            state = await control.get_control_state(self.camera)

        self.assertTrue(state["image_bright_supported"])
        self.assertEqual(state["image_brightness"], 128)

    async def test_send_control_image_forwards_to_onvif_imaging(self):
        with patch.object(control.onvif_control, "set_image_adjustments") as set_adjustments:
            result = await control.send_control(self.camera, action="image", bright="128")

        set_adjustments.assert_called_once_with(
            host="192.0.2.30", port=80, username="camera", password="secret", values={"bright": 128.0}
        )
        self.assertEqual(result, {"status": "ok", "action": "image"})

    async def test_send_control_daynight_forwards_to_onvif_imaging(self):
        with patch.object(control.onvif_control, "set_daynight_mode") as set_mode:
            result = await control.send_control(self.camera, action="daynight", mode="Auto")

        set_mode.assert_called_once_with(host="192.0.2.30", port=80, username="camera", password="secret", mode="Auto")
        self.assertEqual(result, {"status": "ok", "action": "daynight"})

    async def test_send_control_hdr_forwards_to_onvif_imaging(self):
        with patch.object(control.onvif_control, "set_hdr_state") as set_hdr:
            result = await control.send_control(self.camera, action="hdr", state=True)

        set_hdr.assert_called_once_with(host="192.0.2.30", port=80, username="camera", password="secret", state=True)
        self.assertEqual(result, {"status": "ok", "action": "hdr"})


if __name__ == "__main__":
    unittest.main()
