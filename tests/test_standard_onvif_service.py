import unittest
from unittest.mock import patch

from app.tbc.camera_modules.onvif import OnvifProbe
from app.tbc.standard_onvif import service


class StandardOnvifServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_uses_discovered_stream_and_adds_credentials(self):
        camera = {
            "host": "192.0.2.30",
            "username": "camera user",
            "password": "p@ss",
            "onvif_port": 80,
        }
        onvif = OnvifProbe(
            success=True,
            message="ONVIF-Verbindung erfolgreich",
            manufacturer="Generic",
            model="IPC",
            stream_uris=["rtsp://192.0.2.30:554/main"],
            event_detection_keys={"motion"},
        )

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(snapshot.stream_uri, "rtsp://camera%20user:p%40ss@192.0.2.30:554/main")
        motion = next(row for row in snapshot.detections if row["key"] == "motion")
        self.assertTrue(motion["supported"])

    async def test_probe_requires_successful_onvif_connection(self):
        onvif = OnvifProbe(False, "ONVIF-Verbindung fehlgeschlagen")
        camera = {"host": "192.0.2.30", "username": "camera", "password": "secret", "onvif_port": 80}

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "error")
        self.assertIsNone(snapshot.stream_uri)


if __name__ == "__main__":
    unittest.main()
