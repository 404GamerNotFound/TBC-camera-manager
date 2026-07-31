import io
import unittest
from unittest.mock import MagicMock

import numpy as np

from app.tbc.detection.audio_source import SAMPLE_RATE, WINDOW_SAMPLES, AudioGrabber


class _FakeProcess:
    def __init__(self, stdout: bytes) -> None:
        self.stdout = io.BytesIO(stdout)
        self._returncode = None

    def poll(self):
        return self._returncode


class AudioGrabberTests(unittest.TestCase):
    def test_sample_rate_and_window_are_yamnet_compatible(self):
        self.assertEqual(SAMPLE_RATE, 16000)
        self.assertEqual(WINDOW_SAMPLES, 15360)

    def test_read_window_returns_normalized_float32_samples(self):
        grabber = AudioGrabber("rtsp://example/stream")
        raw_samples = np.full(WINDOW_SAMPLES, 16384, dtype=np.int16)  # 0.5 in [-1, 1]
        grabber._process = _FakeProcess(raw_samples.tobytes())
        window = grabber.read_window()
        self.assertIsNotNone(window)
        self.assertEqual(window.shape, (WINDOW_SAMPLES,))
        self.assertEqual(window.dtype, np.float32)
        self.assertAlmostEqual(float(window[0]), 0.5, places=3)

    def test_read_window_returns_none_on_short_read(self):
        grabber = AudioGrabber("rtsp://example/stream")
        # Fewer bytes than one full window - simulates a stream with no audio track,
        # where ffmpeg exits almost immediately with little or no output.
        grabber._process = _FakeProcess(b"\x00\x00")
        window = grabber.read_window()
        self.assertIsNone(window)

    def test_read_window_returns_none_without_a_started_process(self):
        grabber = AudioGrabber("rtsp://example/stream")
        self.assertIsNone(grabber.read_window())

    def test_is_running_reflects_process_state(self):
        grabber = AudioGrabber("rtsp://example/stream")
        process = _FakeProcess(b"")
        grabber._process = process
        self.assertTrue(grabber.is_running())
        process._returncode = 1
        self.assertFalse(grabber.is_running())

    def test_stop_terminates_the_process(self):
        grabber = AudioGrabber("rtsp://example/stream")
        process = MagicMock()
        process.poll.return_value = None
        grabber._process = process
        grabber.stop()
        process.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
