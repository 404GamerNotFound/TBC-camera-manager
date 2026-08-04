import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from app.tbc.detection.hailo_backend import (
    HailoBackend,
    HailoModelMetadata,
    decode_hailo_nms_output,
)


def _metadata_file(tmp: str) -> str:
    path = Path(tmp) / "hailo.json"
    path.write_text(
        json.dumps({"input_size": [640, 640], "classes": {"0": "person", "2": "car", "16": "dog"}}),
        encoding="utf-8",
    )
    return str(path)


def _metadata(tmp: str) -> HailoModelMetadata:
    return HailoModelMetadata.load(Path(_metadata_file(tmp)))


class HailoAvailabilityTests(unittest.TestCase):
    def test_unavailable_when_hailo_platform_not_installed(self):
        # hailo_platform (HailoRT's Python bindings) is not installed in this
        # environment - no public PyPI wheel exists, see Dockerfile.hailo - this
        # exercises the real fallback path every non-Hailo TBC install hits.
        available, message = HailoBackend.available()
        self.assertFalse(available)
        self.assertIn("hailo_platform", message)

    def test_unavailable_when_device_init_fails(self):
        fake_module = types.SimpleNamespace(VDevice=MagicMock(side_effect=RuntimeError("no Hailo device found")))
        with patch.dict("sys.modules", {"hailo_platform": fake_module}):
            available, message = HailoBackend.available()
        self.assertFalse(available)
        self.assertIn("no Hailo device found", message)

    def test_available_when_device_initializes(self):
        fake_device = MagicMock()
        fake_module = types.SimpleNamespace(VDevice=MagicMock(return_value=fake_device))
        with patch.dict("sys.modules", {"hailo_platform": fake_module}):
            available, _message = HailoBackend.available()
        self.assertTrue(available)
        fake_device.release.assert_called_once()


class DecodeHailoNmsOutputTests(unittest.TestCase):
    def test_maps_known_class_and_orders_box_as_xmin_ymin_xmax_ymax(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        # Per-class nested list, each row (ymin, xmin, ymax, xmax, score) - see
        # decode_hailo_nms_output's docstring for the verified HailoRT contract.
        raw_output = [
            np.array([[0.2, 0.1, 0.7, 0.5, 0.9]], dtype=np.float32),  # class 0: person
            np.empty((0, 5), dtype=np.float32),  # class 1: not in metadata
            np.empty((0, 5), dtype=np.float32),  # class 2: car, none detected
        ]
        detections = decode_hailo_nms_output(raw_output, metadata, confidence_threshold=0.3)
        self.assertEqual(len(detections), 1)
        detection = detections[0]
        self.assertEqual(detection.label, "person")
        self.assertEqual(detection.detection_key, "ai_person")
        self.assertAlmostEqual(detection.confidence, 0.9)
        for actual, expected in zip(detection.box, (0.1, 0.2, 0.5, 0.7)):
            self.assertAlmostEqual(actual, expected, places=5)

    def test_filters_below_confidence_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        raw_output = [np.array([[0.2, 0.1, 0.7, 0.5, 0.2]], dtype=np.float32)]
        detections = decode_hailo_nms_output(raw_output, metadata, confidence_threshold=0.5)
        self.assertEqual(detections, [])

    def test_ignores_classes_without_metadata_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        raw_output = [np.empty((0, 5), dtype=np.float32)] * 15 + [
            np.array([[0.0, 0.0, 0.5, 0.5, 0.9]], dtype=np.float32)  # class 15: not in metadata
        ]
        detections = decode_hailo_nms_output(raw_output, metadata, confidence_threshold=0.3)
        self.assertEqual(detections, [])

    def test_drops_degenerate_boxes(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        raw_output = [np.array([[0.5, 0.5, 0.5, 0.9, 0.9]], dtype=np.float32)]  # ymin == ymax
        detections = decode_hailo_nms_output(raw_output, metadata, confidence_threshold=0.3)
        self.assertEqual(detections, [])

    def test_maps_car_and_dog_to_canonical_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        raw_output = [
            np.empty((0, 5), dtype=np.float32),
            np.empty((0, 5), dtype=np.float32),
            np.array([[0.0, 0.0, 0.5, 0.5, 0.8]], dtype=np.float32),  # class 2: car
        ] + [np.empty((0, 5), dtype=np.float32)] * 13 + [
            np.array([[0.0, 0.0, 0.5, 0.5, 0.7]], dtype=np.float32),  # class 16: dog
        ]
        detections = decode_hailo_nms_output(raw_output, metadata, confidence_threshold=0.3)
        keys = {detection.detection_key for detection in detections}
        self.assertEqual(keys, {"ai_vehicle", "ai_animal"})


class HailoInferTests(unittest.TestCase):
    """infer() itself, with fake VDevice/InferModel/ConfiguredInferModel objects
    standing in for hailo_platform - confirms the binding/run wiring independent
    of decode logic already covered above."""

    def test_infer_creates_bindings_runs_and_decodes_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = HailoBackend("model.hef", _metadata_file(tmp), confidence_threshold=0.3)

        raw_output = [np.array([[0.2, 0.1, 0.7, 0.5, 0.9]], dtype=np.float32)]
        fake_output_stream = MagicMock(shape=(1, 5))
        fake_bindings = MagicMock()
        fake_bindings.output.return_value.get_buffer.return_value = raw_output

        fake_infer_model = MagicMock()
        fake_infer_model.output.return_value = fake_output_stream

        fake_configured_model = MagicMock()
        fake_configured_model.create_bindings.return_value = fake_bindings

        backend._infer_model = fake_infer_model
        backend._configured_model = fake_configured_model
        backend._output_name = "output0"

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        detections = backend.infer(frame)

        fake_configured_model.create_bindings.assert_called_once()
        fake_bindings.input.return_value.set_buffer.assert_called_once()
        fake_configured_model.run.assert_called_once()
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].detection_key, "ai_person")


class HailoModelMetadataTests(unittest.TestCase):
    def test_loads_classes_as_int_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _metadata(tmp)
        self.assertEqual(metadata.input_size, (640, 640))
        self.assertEqual(metadata.classes[0], "person")
        self.assertEqual(metadata.classes[16], "dog")


if __name__ == "__main__":
    unittest.main()
