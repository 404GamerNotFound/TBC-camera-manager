import unittest
from unittest.mock import patch

from app.tbc.camera_modules.onvif import OnvifProbe
from app.tbc.camera_plugins.hikvision import service


class HikvisionServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_hikvision_rtsp_uri_encodes_channel_and_stream_type(self):
        camera = {
            "host": "192.0.2.70",
            "username": "camera user",
            "password": "p@ss/word",
            "rtsp_port": 8554,
        }

        self.assertEqual(
            service.hikvision_rtsp_uri(camera),
            "rtsp://camera%20user:p%40ss%2Fword@192.0.2.70:8554/Streaming/Channels/101",
        )
        self.assertEqual(
            service.hikvision_rtsp_uri(camera, channel=2, stream="sub"),
            "rtsp://camera%20user:p%40ss%2Fword@192.0.2.70:8554/Streaming/Channels/202",
        )

    async def test_probe_prefers_discovered_onvif_stream(self):
        camera = {"host": "192.0.2.70", "username": "camera", "password": "secret", "onvif_port": 80}
        onvif = OnvifProbe(
            success=True,
            message="ONVIF-Verbindung erfolgreich",
            manufacturer="Hikvision",
            model="DS-2CD2143G0",
            stream_uris=["rtsp://192.0.2.70:554/onvif-stream"],
            event_detection_keys={"motion", "line_crossing"},
        )

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(snapshot.stream_uri, "rtsp://camera:secret@192.0.2.70:554/onvif-stream")
        rows = {row["key"]: row for row in snapshot.detections}
        self.assertTrue(rows["line_crossing"]["supported"])

    async def test_probe_falls_back_to_hikvision_rtsp_path_when_onvif_fails(self):
        camera = {"host": "192.0.2.70", "username": "camera", "password": "secret", "onvif_port": 80}
        onvif = OnvifProbe(False, "ONVIF-Verbindung fehlgeschlagen")

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "warn")
        self.assertEqual(snapshot.stream_uri, "rtsp://camera:secret@192.0.2.70:554/Streaming/Channels/101")


if __name__ == "__main__":
    unittest.main()
