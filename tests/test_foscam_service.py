import unittest
from unittest.mock import patch

from app.tbc.camera_modules.onvif import OnvifProbe
from app.tbc.camera_plugins.foscam import service


class FoscamServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_foscam_rtsp_uri_uses_camera_account_and_configured_port(self):
        camera = {
            "host": "192.0.2.60",
            "username": "camera user",
            "password": "p@ss/word",
            "rtsp_port": 8554,
        }

        uri = service.foscam_rtsp_uri(camera)

        self.assertEqual(uri, "rtsp://camera%20user:p%40ss%2Fword@192.0.2.60:8554/videoMain")
        self.assertEqual(
            service.foscam_rtsp_uri(camera, stream="videoSub"),
            "rtsp://camera%20user:p%40ss%2Fword@192.0.2.60:8554/videoSub",
        )

    async def test_probe_prefers_discovered_onvif_stream(self):
        camera = {
            "host": "192.0.2.60",
            "username": "camera",
            "password": "secret",
            "onvif_port": 888,
            "rtsp_port": 554,
        }
        onvif = OnvifProbe(
            success=True,
            message="ONVIF-Verbindung erfolgreich",
            manufacturer="Foscam",
            model="R2",
            stream_uris=["rtsp://192.0.2.60:554/onvif-stream"],
            event_detection_keys={"motion"},
        )

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(snapshot.stream_uri, "rtsp://camera:secret@192.0.2.60:554/onvif-stream")

    async def test_probe_falls_back_to_foscam_rtsp_path_when_onvif_fails(self):
        camera = {"host": "192.0.2.60", "username": "camera", "password": "secret", "onvif_port": 888}
        onvif = OnvifProbe(False, "ONVIF-Verbindung fehlgeschlagen")

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "warn")
        self.assertEqual(snapshot.stream_uri, "rtsp://camera:secret@192.0.2.60:554/videoMain")


if __name__ == "__main__":
    unittest.main()
