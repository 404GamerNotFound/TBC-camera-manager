import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from app.tbc.detection.coral_backend import (
    CoralEdgeTpuBackend,
    CoralModelMetadata,
    decode_edgetpu_detection_output,
)


def _metadata_file(tmp: str) -> str:
    path = Path(tmp) / "coral.json"
    path.write_text(
        json.dumps({"input_size": [300, 300], "classes": {"0": "person", "2": "car", "17": "dog"}}),
        encoding="utf-8",
    )
    return str(path)


def _metadata(tmp: str) -> CoralModelMetadata:
    return CoralModelMetadata.load(Path(_metadata_file(tmp)))


class CoralAvailabilityTests(unittest.TestCase):
    def test_unavailable_when_no_runtime_installed(self):
        # Neither ai-edge-litert nor tflite-runtime is installed in this
        # environment (no Linux Edge TPU runtime here) - this exercises the
        # real fallback path most TBC installs hit.
        available, message = CoralEdgeTpuBackend.available()
        self.assertFalse(available)
        self.assertIn("ai-edge-litert", message)

    def test_unavailable_when_delegate_cannot_load(self):
        fake_litert = types.SimpleNamespace(
            Interpreter=MagicMock(),
            load_delegate=MagicMock(side_effect=OSError("libedgetpu.so.1: cannot open shared object file")),
        )
        with patch.dict(
            "sys.modules", {"ai_edge_litert": MagicMock(), "ai_edge_litert.interpreter": fake_litert}
        ):
            available, message = CoralEdgeTpuBackend.available()
        self.assertFalse(available)
        self.assertIn("Edge TPU runtime", message)

    def test_available_when_delegate_loads(self):
        fake_litert = types.SimpleNamespace(Interpreter=MagicMock(), load_delegate=MagicMock(return_value=object()))
        with patch.dict(
            "sys.modules", {"ai_edge_litert": MagicMock(), "ai_edge_litert.interpreter": fake_litert}
        ):
            available, message = CoralEdgeTpuBackend.available()
        self.assertTrue(available)

    def test_falls_back_to_tflite_runtime_when_ai_edge_litert_missing(self):
        fake_tflite = types.SimpleNamespace(Interpreter=MagicMock(), load_delegate=MagicMock(return_value=object()))
        with patch.dict(
            "sys.modules",
            {"ai_edge_litert": None, "ai_edge_litert.interpreter": None,
             "tflite_runtime": MagicMock(), "tflite_runtime.interpreter": fake_tflite},
        ):
            available, message = CoralEdgeTpuBackend.available()
        self.assertTrue(available)
        fake_tflite.load_delegate.assert_called_once()


class DecodeEdgetpuDetectionOutputTests(unittest.TestCase):
    def test_maps_known_class_and_keeps_already_normalized_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        boxes = np.array([[0.2, 0.1, 0.7, 0.5]], dtype=np.float32)  # ymin, xmin, ymax, xmax
        classes = np.array([0.0], dtype=np.float32)
        scores = np.array([0.9], dtype=np.float32)
        detections = decode_edgetpu_detection_output(boxes, classes, scores, 1, metadata, confidence_threshold=0.3)
        self.assertEqual(len(detections), 1)
        detection = detections[0]
        self.assertEqual(detection.label, "person")
        self.assertEqual(detection.detection_key, "ai_person")
        self.assertAlmostEqual(detection.confidence, 0.9)
        # box is (xmin, ymin, xmax, ymax) - decoded from (ymin, xmin, ymax, xmax)
        for actual, expected in zip(detection.box, (0.1, 0.2, 0.5, 0.7)):
            self.assertAlmostEqual(actual, expected, places=5)

    def test_filters_below_confidence_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        boxes = np.array([[0.2, 0.1, 0.7, 0.5]], dtype=np.float32)
        classes = np.array([0.0], dtype=np.float32)
        scores = np.array([0.2], dtype=np.float32)
        detections = decode_edgetpu_detection_output(boxes, classes, scores, 1, metadata, confidence_threshold=0.5)
        self.assertEqual(detections, [])

    def test_ignores_classes_without_metadata_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        boxes = np.array([[0.0, 0.0, 0.5, 0.5]], dtype=np.float32)
        classes = np.array([99.0], dtype=np.float32)
        scores = np.array([0.9], dtype=np.float32)
        detections = decode_edgetpu_detection_output(boxes, classes, scores, 1, metadata, confidence_threshold=0.3)
        self.assertEqual(detections, [])

    def test_drops_degenerate_boxes(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        boxes = np.array([[0.5, 0.5, 0.5, 0.9]], dtype=np.float32)  # ymin == ymax
        classes = np.array([0.0], dtype=np.float32)
        scores = np.array([0.9], dtype=np.float32)
        detections = decode_edgetpu_detection_output(boxes, classes, scores, 1, metadata, confidence_threshold=0.3)
        self.assertEqual(detections, [])

    def test_maps_car_to_vehicle_and_dog_to_animal(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        boxes = np.array([[0.0, 0.0, 0.5, 0.5], [0.0, 0.0, 0.5, 0.5]], dtype=np.float32)
        classes = np.array([2.0, 17.0], dtype=np.float32)
        scores = np.array([0.8, 0.7], dtype=np.float32)
        detections = decode_edgetpu_detection_output(boxes, classes, scores, 2, metadata, confidence_threshold=0.3)
        keys = {detection.detection_key for detection in detections}
        self.assertEqual(keys, {"ai_vehicle", "ai_animal"})

    def test_respects_reported_detection_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        boxes = np.array([[0.0, 0.0, 0.5, 0.5], [0.0, 0.0, 0.5, 0.5]], dtype=np.float32)
        classes = np.array([0.0, 0.0], dtype=np.float32)
        scores = np.array([0.9, 0.9], dtype=np.float32)
        # Model reports only 1 valid detection even though the fixed-size output
        # arrays hold 2 slots - the second slot must be ignored.
        detections = decode_edgetpu_detection_output(boxes, classes, scores, 1, metadata, confidence_threshold=0.3)
        self.assertEqual(len(detections), 1)


class CoralInferTests(unittest.TestCase):
    """infer() itself, with a fake interpreter standing in for tflite_runtime -
    confirms the input/output tensor wiring (index-based, matching
    TFLite_Detection_PostProcess's fixed contract) independent of decode logic
    already covered above."""

    def test_infer_reads_the_four_output_tensors_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = CoralEdgeTpuBackend("model.tflite", _metadata_file(tmp), confidence_threshold=0.3)
        fake_interpreter = MagicMock()
        fake_interpreter.get_input_details.return_value = [{"index": 0}]
        fake_interpreter.get_output_details.return_value = [{"index": 1}, {"index": 2}, {"index": 3}, {"index": 4}]
        tensors = {
            1: np.array([[[0.2, 0.1, 0.7, 0.5]]], dtype=np.float32),
            2: np.array([[0.0]], dtype=np.float32),
            3: np.array([[0.9]], dtype=np.float32),
            4: np.array([1.0], dtype=np.float32),
        }
        fake_interpreter.get_tensor.side_effect = lambda index: tensors[index]
        backend._interpreter = fake_interpreter

        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        detections = backend.infer(frame)

        fake_interpreter.set_tensor.assert_called_once()
        fake_interpreter.invoke.assert_called_once()
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].detection_key, "ai_person")


class CoralModelMetadataTests(unittest.TestCase):
    def test_loads_classes_as_int_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        self.assertEqual(metadata.input_size, (300, 300))
        self.assertEqual(metadata.classes[0], "person")
        self.assertEqual(metadata.classes[17], "dog")


if __name__ == "__main__":
    unittest.main()
