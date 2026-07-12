import unittest
from unittest.mock import patch

from app.tbc.camera_modules.onvif import OnvifProbe
from app.tbc.camera_plugins.axis import service


class AxisServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_uses_discovered_stream_and_adds_credentials(self):
        camera = {
            "host": "192.0.2.50",
            "username": "camera user",
            "password": "p@ss",
            "onvif_port": 80,
        }
        onvif = OnvifProbe(
            success=True,
            message="ONVIF-Verbindung erfolgreich",
            manufacturer="Axis",
            model="P3245",
            stream_uris=["rtsp://192.0.2.50:554/axis-media/media.amp"],
            event_detection_keys={"motion", "person"},
        )

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(
            snapshot.stream_uri, "rtsp://camera%20user:p%40ss@192.0.2.50:554/axis-media/media.amp"
        )
        rows = {row["key"]: row for row in snapshot.detections}
        self.assertTrue(rows["motion"]["supported"])
        self.assertTrue(rows["person"]["supported"])
        self.assertFalse(rows["vehicle"]["supported"])

    async def test_probe_requires_successful_onvif_connection(self):
        onvif = OnvifProbe(False, "ONVIF-Verbindung fehlgeschlagen")
        camera = {"host": "192.0.2.50", "username": "camera", "password": "secret", "onvif_port": 80}

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "error")
        self.assertIsNone(snapshot.stream_uri)


if __name__ == "__main__":
    unittest.main()
