import unittest

from app.tbc.camera_modules.streams import validate_manual_stream_uri


class ManualRtspProfileTests(unittest.IsolatedAsyncioTestCase):
    def test_manual_stream_validation_accepts_rtsp_and_rtsps(self):
        self.assertEqual(validate_manual_stream_uri("rtsp://camera/stream"), "rtsp://camera/stream")
        self.assertEqual(validate_manual_stream_uri("rtsps://camera/stream"), "rtsps://camera/stream")

    def test_manual_stream_validation_rejects_http_and_control_characters(self):
        with self.assertRaises(ValueError):
            validate_manual_stream_uri("https://camera/stream")
        with self.assertRaises(ValueError):
            validate_manual_stream_uri("rtsp://camera/stream\nInjected")

if __name__ == "__main__":
    unittest.main()
