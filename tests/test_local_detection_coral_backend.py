import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.tbc.detection.coral_backend import CoralEdgeTpuBackend, CoralModelMetadata


def _fake_object(class_id: float, score: float, xmin: float, ymin: float, xmax: float, ymax: float):
    bbox = types.SimpleNamespace(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)
    return types.SimpleNamespace(id=class_id, score=score, bbox=bbox)


def _metadata_file(tmp: str) -> str:
    path = Path(tmp) / "coral.json"
    path.write_text(
        json.dumps({"input_size": [300, 300], "classes": {"0": "person", "2": "car", "17": "dog"}}),
        encoding="utf-8",
    )
    return str(path)


class CoralAvailabilityTests(unittest.TestCase):
    def test_unavailable_when_pycoral_not_installed(self):
        # pycoral is genuinely not installed in this environment (no Linux Edge TPU
        # runtime here) - this exercises the real fallback path most TBC installs hit.
        available, message = CoralEdgeTpuBackend.available()
        self.assertFalse(available)
        self.assertIn("pycoral", message)

    def test_unavailable_when_no_tpu_device_found(self):
        fake_edgetpu = MagicMock()
        fake_edgetpu.list_edge_tpus.return_value = []
        fake_pycoral_utils = types.ModuleType("pycoral.utils")
        fake_pycoral_utils.edgetpu = fake_edgetpu
        with patch.dict("sys.modules", {"pycoral": MagicMock(), "pycoral.utils": fake_pycoral_utils, "pycoral.utils.edgetpu": fake_edgetpu}):
            available, message = CoralEdgeTpuBackend.available()
        self.assertFalse(available)
        self.assertIn("Edge-TPU-Gerät", message)

    def test_available_when_tpu_device_found(self):
        fake_edgetpu = MagicMock()
        fake_edgetpu.list_edge_tpus.return_value = [{"type": "usb"}]
        with patch.dict("sys.modules", {"pycoral": MagicMock(), "pycoral.utils": MagicMock(), "pycoral.utils.edgetpu": fake_edgetpu}):
            available, message = CoralEdgeTpuBackend.available()
        self.assertTrue(available)


class CoralToDetectionsTests(unittest.TestCase):
    def _backend(self, tmp: str) -> CoralEdgeTpuBackend:
        return CoralEdgeTpuBackend("does-not-need-to-exist.tflite", _metadata_file(tmp), confidence_threshold=0.3)

    def test_maps_known_class_and_normalizes_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self._backend(tmp)
            objects = [_fake_object(0, 0.9, 30, 60, 150, 210)]
            detections = backend._to_detections(objects, width=300, height=300)
        self.assertEqual(len(detections), 1)
        detection = detections[0]
        self.assertEqual(detection.label, "person")
        self.assertEqual(detection.detection_key, "ai_person")
        self.assertAlmostEqual(detection.confidence, 0.9)
        self.assertAlmostEqual(detection.box[0], 0.1)
        self.assertAlmostEqual(detection.box[1], 0.2)
        self.assertAlmostEqual(detection.box[2], 0.5)
        self.assertAlmostEqual(detection.box[3], 0.7)

    def test_ignores_classes_without_metadata_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self._backend(tmp)
            objects = [_fake_object(99, 0.9, 0, 0, 100, 100)]
            detections = backend._to_detections(objects, width=300, height=300)
        self.assertEqual(detections, [])

    def test_drops_degenerate_boxes(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self._backend(tmp)
            objects = [_fake_object(0, 0.9, 100, 100, 100, 200)]
            detections = backend._to_detections(objects, width=300, height=300)
        self.assertEqual(detections, [])

    def test_maps_car_to_vehicle_and_dog_to_animal(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self._backend(tmp)
            objects = [_fake_object(2, 0.8, 0, 0, 50, 50), _fake_object(17, 0.7, 0, 0, 50, 50)]
            detections = backend._to_detections(objects, width=300, height=300)
        keys = {detection.detection_key for detection in detections}
        self.assertEqual(keys, {"ai_vehicle", "ai_animal"})


class CoralModelMetadataTests(unittest.TestCase):
    def test_loads_classes_as_int_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = CoralModelMetadata.load(Path(_metadata_file(tmp)))
        self.assertEqual(metadata.input_size, (300, 300))
        self.assertEqual(metadata.classes[0], "person")
        self.assertEqual(metadata.classes[17], "dog")


if __name__ == "__main__":
    unittest.main()
