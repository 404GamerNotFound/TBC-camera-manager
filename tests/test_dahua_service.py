import unittest
from unittest.mock import patch

from app.tbc.camera_modules.onvif import OnvifProbe
from app.tbc.camera_plugins.dahua import service


class DahuaServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_dahua_rtsp_uri_encodes_channel_and_subtype(self):
        camera = {
            "host": "192.0.2.80",
            "username": "camera user",
            "password": "p@ss/word",
            "rtsp_port": 8554,
        }

        self.assertEqual(
            service.dahua_rtsp_uri(camera),
            "rtsp://camera%20user:p%40ss%2Fword@192.0.2.80:8554/cam/realmonitor?channel=1&subtype=0",
        )
        self.assertEqual(
            service.dahua_rtsp_uri(camera, channel=3, stream="sub"),
            "rtsp://camera%20user:p%40ss%2Fword@192.0.2.80:8554/cam/realmonitor?channel=3&subtype=1",
        )

    async def test_probe_prefers_discovered_onvif_stream(self):
        camera = {"host": "192.0.2.80", "username": "camera", "password": "secret", "onvif_port": 80}
        onvif = OnvifProbe(
            success=True,
            message="ONVIF-Verbindung erfolgreich",
            manufacturer="Dahua",
            model="IPC-HDW",
            stream_uris=["rtsp://192.0.2.80:554/onvif-stream"],
            event_detection_keys={"motion"},
        )

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(snapshot.stream_uri, "rtsp://camera:secret@192.0.2.80:554/onvif-stream")

    async def test_probe_falls_back_to_dahua_rtsp_path_when_onvif_fails(self):
        camera = {"host": "192.0.2.80", "username": "camera", "password": "secret", "onvif_port": 80}
        onvif = OnvifProbe(False, "ONVIF-Verbindung fehlgeschlagen")

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "warn")
        self.assertEqual(
            snapshot.stream_uri, "rtsp://camera:secret@192.0.2.80:554/cam/realmonitor?channel=1&subtype=0"
        )


if __name__ == "__main__":
    unittest.main()
