import unittest
from pathlib import Path

from app.tbc.live import _is_nonfatal_hls_warning, _live_ffmpeg_command


class LiveTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
