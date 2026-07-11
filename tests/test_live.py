import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.tbc.live import LiveManager, _is_nonfatal_hls_warning, _live_ffmpeg_command, redact_rtsp_credentials


class LiveTests(unittest.TestCase):
    def test_redact_rtsp_credentials_masks_username_and_password(self):
        uri = "rtsp://user:pw@192.168.1.236:554/Preview_01_sub"

        self.assertEqual(
            redact_rtsp_credentials(uri),
            "rtsp://***:***@192.168.1.236:554/Preview_01_sub",
        )

    def test_redact_rtsp_credentials_masks_urls_inside_messages(self):
        message = "Fehler bei rtsp://user:pw@camera.local/stream: Verbindung fehlgeschlagen"

        self.assertNotIn("user:pw", redact_rtsp_credentials(message))

    def test_redact_rtsps_credentials_masks_username_and_password(self):
        self.assertEqual(
            redact_rtsp_credentials("rtsps://secure:secret@nvr.local:7441/camera"),
            "rtsps://***:***@nvr.local:7441/camera",
        )

    def test_live_ffmpeg_command_generates_timestamps(self):
        command = _live_ffmpeg_command(
            "rtsp://example/stream",
            Path("/tmp/live/segment%03d.ts"),
            Path("/tmp/live/index.m3u8"),
        )

        self.assertIn("+genpts+discardcorrupt", command)
        self.assertIn("-use_wallclock_as_timestamps", command)
        self.assertIn("-avoid_negative_ts", command)

    def test_hls_unset_timestamp_warning_is_nonfatal(self):
        message = "[hls @ 0x55b196e0d0] Timestamps are unset in a packet for stream 0"

        self.assertTrue(_is_nonfatal_hls_warning(message))
        self.assertFalse(_is_nonfatal_hls_warning("Connection refused"))

    def test_live_message_hides_nonfatal_hls_warning(self):
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            manager._messages["camera-1"] = [
                "Starte Live-Stream camera-1",
                "[hls @ 0x55b196e0d0] Timestamps are unset in a packet for stream 0",
            ]

            self.assertEqual(manager.message("camera-1"), "Starte Live-Stream camera-1")


if __name__ == "__main__":
    unittest.main()
