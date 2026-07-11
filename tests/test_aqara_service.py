import unittest
from unittest.mock import patch

from app.tbc.aqara import service
from app.tbc.camera_modules.onvif import OnvifProbe


CAMERA = {
    "host": "192.0.2.40",
    "username": "aqara",
    "password": "secret",
    "onvif_port": 5000,
    "rtsp_port": 8554,
}


class AqaraServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_g410_style_rtsp_fallback_is_used_when_reachable(self):
        with patch.object(service, "probe_onvif", return_value=OnvifProbe(False, "kein ONVIF")):
            with patch.object(service, "probe_rtsp_stream", return_value=("ok", "RTSP-Stream erreichbar")):
                snapshot = await service.probe_camera(CAMERA)

        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(snapshot.stream_uri, "rtsp://aqara:secret@192.0.2.40:8554/ch1")
        self.assertIn("G410", snapshot.message)

    async def test_g4_style_device_without_onvif_or_rtsp_is_reported_unsupported(self):
        with patch.object(service, "probe_onvif", return_value=OnvifProbe(False, "kein ONVIF")):
            with patch.object(service, "probe_rtsp_stream", return_value=("error", "nicht erreichbar")):
                snapshot = await service.probe_camera(CAMERA)

        self.assertEqual(snapshot.status, "error")
        self.assertIsNone(snapshot.stream_uri)
        self.assertIn("G4 unterstützt kein RTSP", snapshot.message)

    async def test_onvif_stream_is_preferred_for_compatible_aqara_camera(self):
        onvif = OnvifProbe(
            True,
            "ONVIF-Verbindung erfolgreich",
            model="Camera Hub",
            stream_uris=["rtsp://192.0.2.40:554/live"],
        )
        with patch.object(service, "probe_onvif", return_value=onvif):
            with patch.object(service, "probe_rtsp_stream", return_value=("error", "nicht erreichbar")):
                snapshot = await service.probe_camera(CAMERA)

        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(snapshot.stream_uri, "rtsp://aqara:secret@192.0.2.40:554/live")


if __name__ == "__main__":
    unittest.main()
