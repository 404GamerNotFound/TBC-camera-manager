import unittest

from app.tbc.detection.line_crossing import LineCrossingTracker, crossing_side, segments_intersect
from app.tbc.detection.tracking import TrackedDetection


def _tracked(track_id: int, box: tuple[float, float, float, float], detection_key: str = "ai_person") -> TrackedDetection:
    return TrackedDetection(label="person", detection_key=detection_key, confidence=0.9, box=box, track_id=track_id)


def _box_at(x_center: float, y_center: float = 0.5) -> tuple[float, float, float, float]:
    return (x_center - 0.05, y_center - 0.05, x_center + 0.05, y_center + 0.05)


class SegmentsIntersectTests(unittest.TestCase):
    def test_crossing_segments_intersect(self):
        self.assertTrue(segments_intersect((0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0)))

    def test_parallel_segments_do_not_intersect(self):
        self.assertFalse(segments_intersect((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)))

    def test_disjoint_segments_do_not_intersect(self):
        self.assertFalse(segments_intersect((0.0, 0.0), (0.2, 0.2), (0.8, 0.8), (1.0, 1.0)))

    def test_touching_endpoint_counts_as_intersecting(self):
        self.assertTrue(segments_intersect((0.0, 0.0), (0.5, 0.5), (0.5, 0.5), (1.0, 0.0)))

    def test_collinear_overlapping_segments_intersect(self):
        self.assertTrue(segments_intersect((0.0, 0.0), (1.0, 0.0), (0.5, 0.0), (1.5, 0.0)))


class CrossingSideTests(unittest.TestCase):
    def test_sign_flips_across_the_line(self):
        line_p1, line_p2 = (0.0, 0.0), (1.0, 0.0)
        above = crossing_side((0.5, 1.0), line_p1, line_p2)
        below = crossing_side((0.5, -1.0), line_p1, line_p2)
        self.assertGreater(above, 0)
        self.assertLess(below, 0)

    def test_sign_depends_on_draw_order(self):
        point = (0.5, 1.0)
        forward = crossing_side(point, (0.0, 0.0), (1.0, 0.0))
        reversed_ = crossing_side(point, (1.0, 0.0), (0.0, 0.0))
        self.assertGreater(forward, 0)
        self.assertLess(reversed_, 0)


def _line_zone(zone_id: int = 1, classes=None) -> dict:
    return {"id": zone_id, "mode": "line", "points": [[0.5, 0.0], [0.5, 1.0]], "classes": classes}


class LineCrossingTrackerTests(unittest.TestCase):
    def test_a_track_walking_straight_across_fires_one_crossing_with_expected_direction(self):
        tracker = LineCrossingTracker()
        zones = [_line_zone()]
        # Track moves left-to-right across the vertical line at x=0.5.
        self.assertEqual(tracker.update([_tracked(1, _box_at(0.3))], zones, now=0.0), [])
        crossings = tracker.update([_tracked(1, _box_at(0.7))], zones, now=1.0)
        self.assertEqual(len(crossings), 1)
        zone_id, detection_key, direction = crossings[0]
        self.assertEqual(zone_id, 1)
        self.assertEqual(detection_key, "ai_person")
        self.assertIn(direction, ("in", "out"))

    def test_opposite_direction_reports_the_opposite_side(self):
        tracker_forward = LineCrossingTracker()
        tracker_backward = LineCrossingTracker()
        zones = [_line_zone()]
        tracker_forward.update([_tracked(1, _box_at(0.3))], zones, now=0.0)
        forward = tracker_forward.update([_tracked(1, _box_at(0.7))], zones, now=1.0)
        tracker_backward.update([_tracked(1, _box_at(0.7))], zones, now=0.0)
        backward = tracker_backward.update([_tracked(1, _box_at(0.3))], zones, now=1.0)
        self.assertNotEqual(forward[0][2], backward[0][2])

    def test_a_track_that_approaches_and_retreats_without_crossing_fires_nothing(self):
        tracker = LineCrossingTracker()
        zones = [_line_zone()]
        tracker.update([_tracked(1, _box_at(0.3))], zones, now=0.0)
        crossings = tracker.update([_tracked(1, _box_at(0.4))], zones, now=1.0)
        self.assertEqual(crossings, [])

    def test_different_track_ids_do_not_interfere(self):
        tracker = LineCrossingTracker()
        zones = [_line_zone()]
        tracker.update([_tracked(1, _box_at(0.3)), _tracked(2, _box_at(0.7))], zones, now=0.0)
        crossings = tracker.update([_tracked(1, _box_at(0.7)), _tracked(2, _box_at(0.3))], zones, now=1.0)
        self.assertEqual(len(crossings), 2)
        zone_ids = {item[0] for item in crossings}
        self.assertEqual(zone_ids, {1})

    def test_zones_in_other_modes_are_ignored(self):
        tracker = LineCrossingTracker()
        zones = [{"id": 1, "mode": "include", "points": [[0.5, 0.0], [0.5, 1.0], [0.6, 0.5]], "classes": None}]
        tracker.update([_tracked(1, _box_at(0.3))], zones, now=0.0)
        crossings = tracker.update([_tracked(1, _box_at(0.7))], zones, now=1.0)
        self.assertEqual(crossings, [])

    def test_class_filter_only_matches_configured_classes(self):
        tracker = LineCrossingTracker()
        zones = [_line_zone(classes=["ai_vehicle"])]
        tracker.update([_tracked(1, _box_at(0.3), detection_key="ai_person")], zones, now=0.0)
        crossings = tracker.update([_tracked(1, _box_at(0.7), detection_key="ai_person")], zones, now=1.0)
        self.assertEqual(crossings, [])

    def test_active_trigger_keys_reports_a_crossing_only_for_a_brief_window(self):
        tracker = LineCrossingTracker()
        zones = [_line_zone()]
        tracker.update([_tracked(1, _box_at(0.3))], zones, now=0.0)
        crossings = tracker.update([_tracked(1, _box_at(0.7))], zones, now=1.0)
        direction = crossings[0][2]
        expected_key = f"ai_person_line_{direction}"
        self.assertIn(expected_key, tracker.active_trigger_keys(now=1.5))
        self.assertNotIn(expected_key, tracker.active_trigger_keys(now=10.0))


if __name__ == "__main__":
    unittest.main()
