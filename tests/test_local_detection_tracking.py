import unittest

from app.tbc.detection.backend import Detection
from app.tbc.detection.tracking import ObjectTracker


def _detection(key: str, cx: float, cy: float, *, confidence: float = 0.9, half: float = 0.05) -> Detection:
    return Detection(
        label=key,
        detection_key=key,
        confidence=confidence,
        box=(cx - half, cy - half, cx + half, cy + half),
    )


class ObjectTrackerTests(unittest.TestCase):
    def test_single_frame_detection_is_not_confirmed(self):
        tracker = ObjectTracker(min_hits=2)
        confirmed = tracker.update([_detection("ai_person", 0.5, 0.5)])
        self.assertEqual(confirmed, [])

    def test_detection_confirmed_after_min_hits_reached(self):
        tracker = ObjectTracker(min_hits=2)
        tracker.update([_detection("ai_person", 0.5, 0.5)])
        confirmed = tracker.update([_detection("ai_person", 0.51, 0.51)])
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0].detection_key, "ai_person")

    def test_same_object_keeps_same_track_id_across_frames(self):
        tracker = ObjectTracker(min_hits=1)
        first = tracker.update([_detection("ai_person", 0.5, 0.5)])
        second = tracker.update([_detection("ai_person", 0.51, 0.51)])
        third = tracker.update([_detection("ai_person", 0.52, 0.52)])
        self.assertEqual({first[0].track_id, second[0].track_id, third[0].track_id}, {first[0].track_id})

    def test_non_overlapping_detections_of_same_class_get_different_track_ids(self):
        tracker = ObjectTracker(min_hits=1)
        first = tracker.update([_detection("ai_person", 0.1, 0.1)])
        second = tracker.update([_detection("ai_person", 0.1, 0.1), _detection("ai_person", 0.9, 0.9)])
        ids = {d.track_id for d in second}
        self.assertEqual(len(ids), 2)
        self.assertIn(first[0].track_id, ids)

    def test_different_classes_never_share_a_track_even_with_overlapping_boxes(self):
        tracker = ObjectTracker(min_hits=1)
        tracker.update([_detection("ai_person", 0.5, 0.5)])
        confirmed = tracker.update([_detection("ai_vehicle", 0.5, 0.5)])
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0].detection_key, "ai_vehicle")

    def test_track_survives_missed_frames_within_max_missed(self):
        tracker = ObjectTracker(min_hits=1, max_missed=2)
        first = tracker.update([_detection("ai_person", 0.5, 0.5)])
        tracker.update([])  # one missed frame
        third = tracker.update([_detection("ai_person", 0.51, 0.51)])
        self.assertEqual(first[0].track_id, third[0].track_id)

    def test_track_dropped_after_exceeding_max_missed(self):
        tracker = ObjectTracker(min_hits=1, max_missed=1)
        first = tracker.update([_detection("ai_person", 0.5, 0.5)])
        tracker.update([])
        tracker.update([])  # exceeds max_missed
        third = tracker.update([_detection("ai_person", 0.51, 0.51)])
        self.assertNotEqual(first[0].track_id, third[0].track_id)

    def test_person_leaving_and_new_person_entering_get_different_ids(self):
        tracker = ObjectTracker(min_hits=1, max_missed=0)
        first = tracker.update([_detection("ai_person", 0.1, 0.1)])
        tracker.update([])  # first person leaves, immediately dropped (max_missed=0)
        second = tracker.update([_detection("ai_person", 0.9, 0.9)])
        self.assertNotEqual(first[0].track_id, second[0].track_id)


if __name__ == "__main__":
    unittest.main()
