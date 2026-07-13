import unittest

from app.tbc.camera_modules.detections import normalize_detection_key


class DetectionCatalogTests(unittest.TestCase):
    def test_onvif_event_tokens_are_normalized(self):
        self.assertEqual(normalize_detection_key(["RuleEngine", "CellMotionDetector", "Motion"]), "motion")
        self.assertEqual(normalize_detection_key(["AI", "People"]), "person")
        self.assertEqual(normalize_detection_key(["Smart", "CrossLine", "Vehicle"]), "crossline_vehicle")
        self.assertEqual(normalize_detection_key(["Doorbell", "Visitor"]), "visitor")
        self.assertEqual(normalize_detection_key(["Legacy", "Left Item"]), "forgotten_item")
        self.assertEqual(normalize_detection_key(["RuleEngine", "Occupancy"]), "presence")
        self.assertEqual(normalize_detection_key(["VideoSource", "Tamper"]), "tamper")


if __name__ == "__main__":
    unittest.main()
