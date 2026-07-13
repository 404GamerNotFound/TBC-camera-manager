import unittest

from app.tbc.detection.backend import Detection
from app.tbc.detection.supervisor import ActiveObjectTracker


def _detection(key: str, confidence: float = 0.9) -> Detection:
    return Detection(label=key, detection_key=key, confidence=confidence, box=(0.1, 0.1, 0.4, 0.4))


class ActiveObjectTrackerTests(unittest.TestCase):
    def test_reports_all_canonical_keys_every_cycle(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        rows = tracker.detection_rows(now=0.0)
        self.assertEqual({row["key"] for row in rows}, {"person", "vehicle", "animal"})
        self.assertTrue(all(row["active"] is False for row in rows))
        self.assertTrue(all(row["source"] == "local_ai" for row in rows))

    def test_seen_detection_becomes_active(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        tracker.update([_detection("person", 0.87)], now=10.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=10.0)}
        self.assertTrue(rows["person"]["active"])
        self.assertFalse(rows["vehicle"]["active"])
        self.assertEqual(rows["person"]["raw_value"]["confidence"], 0.87)

    def test_stays_active_within_timeout_after_last_sighting(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        tracker.update([_detection("person")], now=10.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=12.5)}
        self.assertTrue(rows["person"]["active"])

    def test_becomes_inactive_after_timeout_elapses(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        tracker.update([_detection("person")], now=10.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=14.0)}
        self.assertFalse(rows["person"]["active"])
        self.assertIsNone(rows["person"]["raw_value"])

    def test_a_single_missed_cycle_does_not_flap_active_state(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        tracker.update([_detection("person")], now=10.0)
        tracker.update([], now=11.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=11.0)}
        self.assertTrue(rows["person"]["active"])

    def test_independent_keys_track_separately(self):
        tracker = ActiveObjectTracker(active_timeout_seconds=3.0)
        tracker.update([_detection("person")], now=1.0)
        tracker.update([_detection("vehicle")], now=5.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=5.0)}
        self.assertFalse(rows["person"]["active"])
        self.assertTrue(rows["vehicle"]["active"])


if __name__ == "__main__":
    unittest.main()
