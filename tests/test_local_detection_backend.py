import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from app.tbc.detection.classes import canonical_detection_key
from app.tbc.detection.onnx_backend import ModelMetadata, OnnxGpuBackend, decode_detection_output, preprocess_frame


def _metadata(**overrides):
    defaults = dict(
        input_name="image_tensor:0",
        input_size=(300, 300),
        input_dtype="uint8",
        output_boxes="detection_boxes:0",
        output_scores="detection_scores:0",
        output_classes="detection_classes:0",
        output_num="num_detections:0",
        classes={1: "person", 3: "car", 18: "dog"},
    )
    defaults.update(overrides)
    return ModelMetadata(**defaults)


class DecodeDetectionOutputTests(unittest.TestCase):
    def test_decodes_boxes_above_threshold_into_known_classes(self):
        metadata = _metadata()
        outputs = {
            "detection_boxes:0": np.array([[[0.1, 0.2, 0.5, 0.6], [0.0, 0.0, 0.9, 0.9]]], dtype=np.float32),
            "detection_scores:0": np.array([[0.9, 0.8]], dtype=np.float32),
            "detection_classes:0": np.array([[1, 3]], dtype=np.float32),
            "num_detections:0": np.array([2.0], dtype=np.float32),
        }
        detections = decode_detection_output(outputs, metadata, confidence_threshold=0.5)
        self.assertEqual(len(detections), 2)
        self.assertEqual(detections[0].label, "person")
        self.assertEqual(detections[0].detection_key, "ai_person")
        self.assertAlmostEqual(detections[0].confidence, 0.9)
        # box is (xmin, ymin, xmax, ymax) - decoded from (ymin, xmin, ymax, xmax)
        for actual, expected in zip(detections[0].box, (0.2, 0.1, 0.6, 0.5)):
            self.assertAlmostEqual(actual, expected, places=5)
        self.assertEqual(detections[1].detection_key, "ai_vehicle")

    def test_filters_below_confidence_threshold(self):
        metadata = _metadata()
        outputs = {
            "detection_boxes:0": np.array([[[0.1, 0.2, 0.5, 0.6]]], dtype=np.float32),
            "detection_scores:0": np.array([[0.3]], dtype=np.float32),
            "detection_classes:0": np.array([[1]], dtype=np.float32),
            "num_detections:0": np.array([1.0], dtype=np.float32),
        }
        detections = decode_detection_output(outputs, metadata, confidence_threshold=0.5)
        self.assertEqual(detections, [])

    def test_ignores_classes_without_a_canonical_mapping(self):
        metadata = _metadata(classes={44: "bottle"})
        outputs = {
            "detection_boxes:0": np.array([[[0.1, 0.2, 0.5, 0.6]]], dtype=np.float32),
            "detection_scores:0": np.array([[0.95]], dtype=np.float32),
            "detection_classes:0": np.array([[44]], dtype=np.float32),
            "num_detections:0": np.array([1.0], dtype=np.float32),
        }
        detections = decode_detection_output(outputs, metadata, confidence_threshold=0.5)
        self.assertEqual(detections, [])

    def test_respects_reported_detection_count(self):
        metadata = _metadata()
        outputs = {
            "detection_boxes:0": np.array([[[0.1, 0.2, 0.5, 0.6], [0.1, 0.2, 0.5, 0.6]]], dtype=np.float32),
            "detection_scores:0": np.array([[0.95, 0.95]], dtype=np.float32),
            "detection_classes:0": np.array([[1, 1]], dtype=np.float32),
            "num_detections:0": np.array([1.0], dtype=np.float32),
        }
        detections = decode_detection_output(outputs, metadata, confidence_threshold=0.5)
        self.assertEqual(len(detections), 1)

    def test_drops_degenerate_boxes(self):
        metadata = _metadata()
        outputs = {
            "detection_boxes:0": np.array([[[0.5, 0.5, 0.5, 0.9]]], dtype=np.float32),
            "detection_scores:0": np.array([[0.95]], dtype=np.float32),
            "detection_classes:0": np.array([[1]], dtype=np.float32),
            "num_detections:0": np.array([1.0], dtype=np.float32),
        }
        detections = decode_detection_output(outputs, metadata, confidence_threshold=0.5)
        self.assertEqual(detections, [])


class PreprocessFrameTests(unittest.TestCase):
    def test_resizes_to_model_input_and_keeps_uint8(self):
        metadata = _metadata(input_size=(64, 48), input_dtype="uint8")
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        tensor = preprocess_frame(frame, metadata)
        self.assertEqual(tensor.shape, (1, 48, 64, 3))
        self.assertEqual(tensor.dtype, np.uint8)

    def test_normalizes_to_float32_when_required(self):
        metadata = _metadata(input_size=(32, 32), input_dtype="float32")
        frame = np.full((100, 100, 3), 255, dtype=np.uint8)
        tensor = preprocess_frame(frame, metadata)
        self.assertEqual(tensor.dtype, np.float32)
        self.assertAlmostEqual(float(tensor.max()), 1.0, places=5)


class CanonicalDetectionKeyTests(unittest.TestCase):
    def test_maps_known_coco_labels(self):
        self.assertEqual(canonical_detection_key("person"), "ai_person")
        self.assertEqual(canonical_detection_key("truck"), "ai_vehicle")
        self.assertEqual(canonical_detection_key("giraffe"), "ai_animal")

    def test_returns_none_for_unmapped_labels(self):
        self.assertIsNone(canonical_detection_key("bottle"))


class OnnxGpuBackendAvailabilityTests(unittest.TestCase):
    def test_unavailable_without_cuda_provider(self):
        fake_onnxruntime = MagicMock()
        fake_onnxruntime.get_available_providers.return_value = ["CPUExecutionProvider"]
        with patch.dict("sys.modules", {"onnxruntime": fake_onnxruntime}):
            available, message = OnnxGpuBackend.available()
        self.assertFalse(available)
        self.assertIn("CUDAExecutionProvider", message)

    def test_available_with_cuda_provider(self):
        fake_onnxruntime = MagicMock()
        fake_onnxruntime.get_available_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        with patch.dict("sys.modules", {"onnxruntime": fake_onnxruntime}):
            available, message = OnnxGpuBackend.available()
        self.assertTrue(available)

    def test_uses_cuda_then_cpu_provider_order(self):
        self.assertEqual(OnnxGpuBackend.providers, ("CUDAExecutionProvider", "CPUExecutionProvider"))


if __name__ == "__main__":
    unittest.main()
