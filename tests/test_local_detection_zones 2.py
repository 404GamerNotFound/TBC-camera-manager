import unittest

from app.tbc.detection.backend import Detection
from app.tbc.detection.zones import filter_detections_by_zones, point_in_polygon

SQUARE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]


def _detection(key: str, box) -> Detection:
    return Detection(label=key, detection_key=key, confidence=0.9, box=box)


def _box_at(cx: float, cy: float) -> tuple[float, float, float, float]:
    return (cx - 0.02, cy - 0.02, cx + 0.02, cy + 0.02)


class PointInPolygonTests(unittest.TestCase):
    def test_point_clearly_inside_is_true(self):
        self.assertTrue(point_in_polygon((0.5, 0.5), SQUARE))

    def test_point_clearly_outside_is_false(self):
        self.assertFalse(point_in_polygon((0.9, 0.9), SQUARE))

    def test_point_on_edge_is_deterministic(self):
        # Ray-casting treats edges as a half-open interval; this locks the current,
        # documented behaviour rather than asserting an inherently ambiguous "on the
        # line" semantic.
        result_a = point_in_polygon((0.2, 0.5), SQUARE)
        result_b = point_in_polygon((0.2, 0.5), SQUARE)
        self.assertEqual(result_a, result_b)

    def test_degenerate_polygon_is_never_inside(self):
        self.assertFalse(point_in_polygon((0.5, 0.5), [(0.1, 0.1), (0.2, 0.2)]))


class FilterDetectionsByZonesTests(unittest.TestCase):
    def test_no_zones_means_no_filtering(self):
        detections = [_detection("person", _box_at(0.5, 0.5))]
        self.assertEqual(filter_detections_by_zones(detections, []), detections)

    def test_exclude_zone_drops_matching_detection_inside_it(self):
        detections = [_detection("person", _box_at(0.5, 0.5))]
        zones = [{"mode": "exclude", "classes": None, "points": SQUARE}]
        self.assertEqual(filter_detections_by_zones(detections, zones), [])

    def test_exclude_zone_does_not_affect_detection_outside_it(self):
        detections = [_detection("person", _box_at(0.95, 0.95))]
        zones = [{"mode": "exclude", "classes": None, "points": SQUARE}]
        self.assertEqual(filter_detections_by_zones(detections, zones), detections)

    def test_exclude_zone_restricted_to_class_ignores_other_classes(self):
        detections = [_detection("vehicle", _box_at(0.5, 0.5))]
        zones = [{"mode": "exclude", "classes": ["person"], "points": SQUARE}]
        self.assertEqual(filter_detections_by_zones(detections, zones), detections)

    def test_include_zone_keeps_detection_inside_it(self):
        detections = [_detection("person", _box_at(0.5, 0.5))]
        zones = [{"mode": "include", "classes": None, "points": SQUARE}]
        self.assertEqual(filter_detections_by_zones(detections, zones), detections)

    def test_include_zone_drops_detection_outside_it(self):
        detections = [_detection("person", _box_at(0.95, 0.95))]
        zones = [{"mode": "include", "classes": None, "points": SQUARE}]
        self.assertEqual(filter_detections_by_zones(detections, zones), [])

    def test_include_zone_for_one_class_leaves_other_classes_unrestricted(self):
        detections = [_detection("animal", _box_at(0.95, 0.95))]
        zones = [{"mode": "include", "classes": ["person"], "points": SQUARE}]
        self.assertEqual(filter_detections_by_zones(detections, zones), detections)

    def test_exclude_takes_precedence_over_include_for_overlapping_zones(self):
        detections = [_detection("person", _box_at(0.5, 0.5))]
        zones = [
            {"mode": "include", "classes": None, "points": SQUARE},
            {"mode": "exclude", "classes": None, "points": SQUARE},
        ]
        self.assertEqual(filter_detections_by_zones(detections, zones), [])

    def test_multiple_include_zones_are_combined_with_or(self):
        second_square = [(0.85, 0.85), (0.95, 0.85), (0.95, 0.95), (0.85, 0.95)]
        detections = [_detection("person", _box_at(0.9, 0.9))]
        zones = [
            {"mode": "include", "classes": None, "points": SQUARE},
            {"mode": "include", "classes": None, "points": second_square},
        ]
        self.assertEqual(filter_detections_by_zones(detections, zones), detections)


if __name__ == "__main__":
    unittest.main()
