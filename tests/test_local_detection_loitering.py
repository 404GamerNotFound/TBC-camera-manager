import unittest

from app.tbc.detection.loitering import LoiterTracker
from app.tbc.detection.tracking import TrackedDetection

SQUARE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]


def _detection(key: str, cx: float = 0.5, cy: float = 0.5, track_id: int = 1) -> TrackedDetection:
    return TrackedDetection(
        label=key,
        detection_key=key,
        confidence=0.9,
        box=(cx - 0.02, cy - 0.02, cx + 0.02, cy + 0.02),
        track_id=track_id,
    )


def _zone(**overrides) -> dict:
    zone = {"id": 1, "mode": "loiter", "classes": None, "points": SQUARE, "min_dwell_seconds": 10}
    zone.update(overrides)
    return zone


class LoiterTrackerTests(unittest.TestCase):
    def test_not_active_before_min_dwell_reached(self):
        tracker = LoiterTracker()
        zones = [_zone()]
        tracker.update([_detection("ai_person")], zones, now=0.0)
        tracker.update([_detection("ai_person")], zones, now=5.0)
        self.assertEqual(tracker.active_loitering_keys(zones, now=5.0), set())

    def test_active_once_min_dwell_reached(self):
        tracker = LoiterTracker()
        zones = [_zone()]
        tracker.update([_detection("ai_person")], zones, now=0.0)
        tracker.update([_detection("ai_person")], zones, now=10.0)
        self.assertEqual(tracker.active_loitering_keys(zones, now=10.0), {"ai_person_loitering"})

    def test_single_missed_frame_within_grace_period_does_not_reset_dwell(self):
        tracker = LoiterTracker()
        zones = [_zone()]
        tracker.update([_detection("ai_person")], zones, now=0.0)
        tracker.update([], zones, now=2.0)  # missed frame, within LOITER_GRACE_SECONDS
        tracker.update([_detection("ai_person")], zones, now=10.0)
        self.assertEqual(tracker.active_loitering_keys(zones, now=10.0), {"ai_person_loitering"})

    def test_absence_beyond_grace_period_resets_dwell(self):
        tracker = LoiterTracker()
        zones = [_zone()]
        tracker.update([_detection("ai_person")], zones, now=0.0)
        tracker.update([], zones, now=10.0)  # far beyond grace period, no detection seen since t=0
        tracker.update([_detection("ai_person")], zones, now=11.0)
        self.assertEqual(tracker.active_loitering_keys(zones, now=11.0), set())

    def test_detection_outside_zone_does_not_accumulate_dwell(self):
        tracker = LoiterTracker()
        zones = [_zone()]
        tracker.update([_detection("ai_person", cx=0.95, cy=0.95)], zones, now=0.0)
        tracker.update([_detection("ai_person", cx=0.95, cy=0.95)], zones, now=10.0)
        self.assertEqual(tracker.active_loitering_keys(zones, now=10.0), set())

    def test_class_restricted_zone_ignores_other_classes(self):
        tracker = LoiterTracker()
        zones = [_zone(classes=["ai_person"])]
        tracker.update([_detection("ai_vehicle")], zones, now=0.0)
        tracker.update([_detection("ai_vehicle")], zones, now=10.0)
        self.assertEqual(tracker.active_loitering_keys(zones, now=10.0), set())

    def test_include_and_exclude_zones_are_not_treated_as_loiter_zones(self):
        tracker = LoiterTracker()
        zones = [{"id": 1, "mode": "include", "classes": None, "points": SQUARE, "min_dwell_seconds": 1}]
        tracker.update([_detection("ai_person")], zones, now=0.0)
        tracker.update([_detection("ai_person")], zones, now=10.0)
        self.assertEqual(tracker.active_loitering_keys(zones, now=10.0), set())

    def test_respects_per_zone_min_dwell_seconds(self):
        tracker = LoiterTracker()
        zones = [_zone(min_dwell_seconds=3)]
        tracker.update([_detection("ai_person")], zones, now=0.0)
        tracker.update([_detection("ai_person")], zones, now=3.0)
        self.assertEqual(tracker.active_loitering_keys(zones, now=3.0), {"ai_person_loitering"})

    def test_different_track_id_does_not_inherit_previous_tracks_dwell(self):
        # One person dwells in the zone, then leaves; a different person (different
        # track_id) enters the same zone moments later. The second one must start its
        # own dwell timer from zero rather than inheriting the first one's presence.
        tracker = LoiterTracker()
        zones = [_zone(min_dwell_seconds=5)]
        tracker.update([_detection("ai_person", track_id=1)], zones, now=0.0)
        tracker.update([_detection("ai_person", track_id=1)], zones, now=4.0)
        # track 1 leaves (grace period elapses) and a new track enters at t=8
        tracker.update([_detection("ai_person", track_id=2)], zones, now=8.0)
        tracker.update([_detection("ai_person", track_id=2)], zones, now=10.0)
        self.assertEqual(tracker.active_loitering_keys(zones, now=10.0), set())

    def test_same_track_id_accumulates_dwell_across_updates(self):
        tracker = LoiterTracker()
        zones = [_zone(min_dwell_seconds=5)]
        tracker.update([_detection("ai_person", track_id=7)], zones, now=0.0)
        tracker.update([_detection("ai_person", track_id=7)], zones, now=6.0)
        self.assertEqual(tracker.active_loitering_keys(zones, now=6.0), {"ai_person_loitering"})


if __name__ == "__main__":
    unittest.main()
