import json
import tempfile
import unittest

from app.tbc import database
from app.tbc.detection.backend import Detection
from app.tbc.detection.supervisor import ActiveObjectTracker


def _detection(key: str, confidence: float = 0.9) -> Detection:
    return Detection(label=key, detection_key=key, confidence=confidence, box=(0.1, 0.1, 0.4, 0.4))


class ActiveObjectTrackerTests(unittest.TestCase):
    def test_reports_all_canonical_keys_every_cycle(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        rows = tracker.detection_rows(now=0.0)
        self.assertEqual({row["key"] for row in rows}, {"ai_person", "ai_vehicle", "ai_animal"})
        self.assertTrue(all(row["active"] is False for row in rows))
        self.assertTrue(all(row["source"] == "local_ai" for row in rows))

    def test_seen_detection_becomes_active(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        tracker.update([_detection("ai_person", 0.87)], now=10.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=10.0)}
        self.assertTrue(rows["ai_person"]["active"])
        self.assertFalse(rows["ai_vehicle"]["active"])
        self.assertIsInstance(rows["ai_person"]["raw_value"], str)
        self.assertEqual(json.loads(rows["ai_person"]["raw_value"])["confidence"], 0.87)

    def test_stays_active_within_timeout_after_last_sighting(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        tracker.update([_detection("ai_person")], now=10.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=12.5)}
        self.assertTrue(rows["ai_person"]["active"])

    def test_becomes_inactive_after_timeout_elapses(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        tracker.update([_detection("ai_person")], now=10.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=14.0)}
        self.assertFalse(rows["ai_person"]["active"])
        self.assertIsNone(rows["ai_person"]["raw_value"])

    def test_a_single_missed_cycle_does_not_flap_active_state(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        tracker.update([_detection("ai_person")], now=10.0)
        tracker.update([], now=11.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=11.0)}
        self.assertTrue(rows["ai_person"]["active"])

    def test_independent_keys_track_separately(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        tracker.update([_detection("ai_person")], now=1.0)
        tracker.update([_detection("ai_vehicle")], now=5.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=5.0)}
        self.assertFalse(rows["ai_person"]["active"])
        self.assertTrue(rows["ai_vehicle"]["active"])


class ActiveObjectTrackerDatabaseIntegrationTests(unittest.TestCase):
    """Locks in that tracker rows are actually storable by database.replace_detections.

    A prior bug put a raw dict in raw_value, which passed the pure-tracker tests above
    (they never touched sqlite) but crashed with "Error binding parameter" once real
    detections reached the database - only caught by an end-to-end run against a real
    camera stream. This test exercises the same contract without needing ffmpeg/a model.
    """

    def test_rows_with_an_active_detection_are_storable(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Test",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
            tracker.update([Detection(label="cat", detection_key="ai_animal", confidence=0.9, box=(0.1, 0.1, 0.4, 0.4))])
            rows = tracker.detection_rows()

            database.replace_detections(handle.name, camera_id, rows)

            stored = {row["detection_key"]: row for row in database.list_detections(handle.name, camera_id)}
            self.assertTrue(bool(stored["ai_animal"]["active"]))
            self.assertEqual(json.loads(stored["ai_animal"]["raw_value"])["confidence"], 0.9)


if __name__ == "__main__":
    unittest.main()
