import unittest

from app.tbc.reolink.catalog import definition_by_key, normalize_detection_key


class DetectionCatalogTests(unittest.TestCase):
    def test_home_assistant_reolink_detection_names_are_present(self):
        expected = {
            "motion",
            "face",
            "person",
            "vehicle",
            "non_motor_vehicle",
            "pet",
            "animal",
            "package",
            "visitor",
            "cry",
            "crossline_person",
            "intrusion_vehicle",
            "linger_dog_cat",
            "forgotten_item",
            "taken_item",
            "io_input",
        }
        missing = {key for key in expected if definition_by_key(key) is None}
        self.assertEqual(missing, set())

    def test_onvif_event_tokens_are_normalized(self):
        self.assertEqual(normalize_detection_key(["RuleEngine", "CellMotionDetector", "Motion"]), "motion")
        self.assertEqual(normalize_detection_key(["AI", "People"]), "person")
        self.assertEqual(normalize_detection_key(["Smart", "CrossLine", "Vehicle"]), "crossline_vehicle")
        self.assertEqual(normalize_detection_key(["Doorbell", "Visitor"]), "visitor")
        self.assertEqual(normalize_detection_key(["Legacy", "Left Item"]), "forgotten_item")


if __name__ == "__main__":
    unittest.main()

