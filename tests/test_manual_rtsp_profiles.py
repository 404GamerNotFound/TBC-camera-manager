import unittest
from unittest.mock import patch

from app.tbc.camera_modules.streams import validate_manual_stream_uri
from app.tbc.sonoff.module import SonoffCameraModule
from app.tbc.ubiquiti.module import UbiquitiCameraModule


CAMERA = {
    "manual_stream_uri": "rtsps://user:secret@nvr.example:7441/camera-id",
}


class ManualRtspProfileTests(unittest.IsolatedAsyncioTestCase):
    def test_manual_stream_validation_accepts_rtsp_and_rtsps(self):
        self.assertEqual(validate_manual_stream_uri("rtsp://camera/stream"), "rtsp://camera/stream")
        self.assertEqual(validate_manual_stream_uri("rtsps://camera/stream"), "rtsps://camera/stream")

    def test_manual_stream_validation_rejects_http_and_control_characters(self):
        with self.assertRaises(ValueError):
            validate_manual_stream_uri("https://camera/stream")
        with self.assertRaises(ValueError):
            validate_manual_stream_uri("rtsp://camera/stream\nInjected")

    async def test_ubiquiti_uses_the_exact_protect_stream_link(self):
        with patch("app.tbc.manual_rtsp.module.probe_rtsp_stream", return_value=("ok", "RTSP-Stream erreichbar")):
            snapshot = await UbiquitiCameraModule().probe(CAMERA)

        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(snapshot.stream_uri, CAMERA["manual_stream_uri"])
        self.assertEqual(snapshot.manufacturer, "Ubiquiti")

    async def test_sonoff_explains_how_to_generate_a_missing_link(self):
        snapshot = await SonoffCameraModule().probe({"manual_stream_uri": ""})

        self.assertEqual(snapshot.status, "error")
        self.assertIn("eWeLink", snapshot.message)


if __name__ == "__main__":
    unittest.main()
