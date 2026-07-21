import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from app.tbc.detection.audio_backend import AudioModelMetadata, OnnxAudioBackend, decode_audio_output
from app.tbc.detection.classes import canonical_audio_detection_key


def _metadata(**overrides):
    defaults = dict(
        input_name="waveform",
        output_name="scores",
        sample_rate=16000,
        window_samples=15360,
        classes={0: "Speech", 1: "Dog", 2: "Bark", 3: "Glass", 4: "Smoke detector, smoke alarm"},
    )
    defaults.update(overrides)
    return AudioModelMetadata(**defaults)


class DecodeAudioOutputTests(unittest.TestCase):
    def test_decodes_scores_above_threshold_into_known_classes(self):
        metadata = _metadata()
        scores = np.array([0.1, 0.9, 0.0, 0.8, 0.0], dtype=np.float32)
        detections = decode_audio_output(scores, metadata, confidence_threshold=0.5)
        keys = {detection.detection_key for detection in detections}
        self.assertEqual(keys, {"ai_bark", "ai_glass_break"})

    def test_filters_below_confidence_threshold(self):
        metadata = _metadata()
        scores = np.array([0.1, 0.2, 0.0, 0.3, 0.0], dtype=np.float32)
        detections = decode_audio_output(scores, metadata, confidence_threshold=0.5)
        self.assertEqual(detections, [])

    def test_ignores_classes_without_a_canonical_mapping(self):
        metadata = _metadata(classes={0: "Speech"})
        scores = np.array([0.95], dtype=np.float32)
        detections = decode_audio_output(scores, metadata, confidence_threshold=0.5)
        self.assertEqual(detections, [])

    def test_multiple_labels_for_same_key_report_the_highest_confidence_once(self):
        # "Dog" and "Bark" both map to ai_bark - only the higher-confidence one should surface.
        metadata = _metadata()
        scores = np.array([0.0, 0.6, 0.9, 0.0, 0.0], dtype=np.float32)
        detections = decode_audio_output(scores, metadata, confidence_threshold=0.5)
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].detection_key, "ai_bark")
        self.assertEqual(detections[0].label, "Bark")
        self.assertAlmostEqual(detections[0].confidence, 0.9)


class CanonicalAudioDetectionKeyTests(unittest.TestCase):
    def test_maps_known_audioset_labels(self):
        self.assertEqual(canonical_audio_detection_key("Dog"), "ai_bark")
        self.assertEqual(canonical_audio_detection_key("Bow-wow"), "ai_bark")
        self.assertEqual(canonical_audio_detection_key("Glass"), "ai_glass_break")
        self.assertEqual(canonical_audio_detection_key("Smoke detector, smoke alarm"), "ai_smoke_alarm")

    def test_returns_none_for_unmapped_labels(self):
        self.assertIsNone(canonical_audio_detection_key("Speech"))


class OnnxAudioBackendAvailabilityTests(unittest.TestCase):
    def test_unavailable_without_onnxruntime(self):
        with patch.dict("sys.modules", {"onnxruntime": None}):
            available, _message = OnnxAudioBackend.available()
        self.assertFalse(available)

    def test_infer_runs_session_with_expected_tensor_shape(self):
        metadata_path_read = _metadata()
        fake_session = MagicMock()
        fake_session.run.return_value = [np.array([0.0, 0.9, 0.0, 0.0, 0.0], dtype=np.float32)]
        with patch.object(OnnxAudioBackend, "load", lambda self: None):
            backend = OnnxAudioBackend.__new__(OnnxAudioBackend)
            backend.metadata = metadata_path_read
            backend.confidence_threshold = 0.5
            backend._session = fake_session
            waveform = np.zeros(15360, dtype=np.float32)
            detections = backend.infer(waveform)
        fake_session.run.assert_called_once()
        called_args, called_kwargs = fake_session.run.call_args
        self.assertEqual(called_args[0], ["scores"])
        self.assertIn("waveform", called_args[1])
        self.assertEqual(called_args[1]["waveform"].shape, (1, 15360))
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].detection_key, "ai_bark")


if __name__ == "__main__":
    unittest.main()
