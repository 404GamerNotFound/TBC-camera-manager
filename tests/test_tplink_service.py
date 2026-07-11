import unittest
from unittest.mock import patch

from app.tbc.camera_modules.onvif import OnvifProbe
from app.tbc.camera_plugins.tplink import service


class TpLinkServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_tapo_rtsp_uri_uses_camera_account_and_configured_port(self):
        camera = {
            "host": "192.0.2.25",
            "username": "camera user",
            "password": "p@ss/word",
            "rtsp_port": 8554,
        }

        uri = service.tapo_rtsp_uri(camera)

        self.assertEqual(uri, "rtsp://camera%20user:p%40ss%2Fword@192.0.2.25:8554/stream1")

    async def test_probe_uses_onvif_metadata_and_tapo_detection_catalog(self):
        camera = {
            "host": "192.0.2.25",
            "username": "camera",
            "password": "secret",
            "onvif_port": 2020,
            "rtsp_port": 554,
        }
        onvif = OnvifProbe(
            success=True,
            message="ONVIF-Verbindung erfolgreich",
            manufacturer="TP-Link",
            model="Tapo C200",
            event_detection_keys={"motion", "person"},
        )

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        rows = {row["key"]: row for row in snapshot.detections}
        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(snapshot.model, "Tapo C200")
        self.assertTrue(rows["motion"]["supported"])
        self.assertTrue(rows["person"]["supported"])
        self.assertFalse(rows["vehicle"]["supported"])


if __name__ == "__main__":
    unittest.main()
