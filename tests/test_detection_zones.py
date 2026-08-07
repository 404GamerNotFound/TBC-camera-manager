import tempfile
import unittest

from app.tbc import database


class DetectionZoneLineModeTests(unittest.TestCase):
    def setUp(self):
        self._tempfile = tempfile.NamedTemporaryFile(suffix=".sqlite3")
        self.db_path = self._tempfile.name
        database.initialize(self.db_path)
        self.camera_id = database.create_camera(
            self.db_path, name="Eingang", host="192.0.2.10", onvif_port=8000, http_port=80, username="a", password="b"
        )

    def tearDown(self):
        self._tempfile.close()

    def test_valid_zone_mode_accepts_line(self):
        zone_id = database.create_camera_detection_zone(
            self.db_path, self.camera_id, name="Tuer", mode="line", classes=None,
            points=[(0.2, 0.5), (0.8, 0.5)], min_dwell_seconds=10,
        )
        zone = database.get_camera_detection_zone(self.db_path, zone_id)
        self.assertEqual(zone["mode"], "line")

    def test_invalid_mode_falls_back_to_include(self):
        zone_id = database.create_camera_detection_zone(
            self.db_path, self.camera_id, name="X", mode="bogus", classes=None,
            points=[(0.1, 0.1), (0.2, 0.2), (0.3, 0.1)], min_dwell_seconds=10,
        )
        zone = database.get_camera_detection_zone(self.db_path, zone_id)
        self.assertEqual(zone["mode"], "include")

    def test_non_line_zones_do_not_carry_crossing_counts(self):
        zone_id = database.create_camera_detection_zone(
            self.db_path, self.camera_id, name="X", mode="include", classes=None,
            points=[(0.1, 0.1), (0.2, 0.2), (0.3, 0.1)], min_dwell_seconds=10,
        )
        zone = database.get_camera_detection_zone(self.db_path, zone_id)
        self.assertNotIn("crossing_in", zone)
        self.assertNotIn("crossing_out", zone)

    def test_line_zones_default_to_zero_counts(self):
        zone_id = database.create_camera_detection_zone(
            self.db_path, self.camera_id, name="Tuer", mode="line", classes=None,
            points=[(0.2, 0.5), (0.8, 0.5)], min_dwell_seconds=10,
        )
        zone = database.get_camera_detection_zone(self.db_path, zone_id)
        self.assertEqual(zone["crossing_in"], 0)
        self.assertEqual(zone["crossing_out"], 0)

    def test_list_camera_detection_zones_also_carries_counts(self):
        zone_id = database.create_camera_detection_zone(
            self.db_path, self.camera_id, name="Tuer", mode="line", classes=None,
            points=[(0.2, 0.5), (0.8, 0.5)], min_dwell_seconds=10,
        )
        database.increment_zone_crossing_count(self.db_path, zone_id, "in")
        zones = database.list_camera_detection_zones(self.db_path, self.camera_id)
        self.assertEqual(zones[0]["crossing_in"], 1)
        self.assertEqual(zones[0]["crossing_out"], 0)


class ZoneCrossingCountTests(unittest.TestCase):
    def setUp(self):
        self._tempfile = tempfile.NamedTemporaryFile(suffix=".sqlite3")
        self.db_path = self._tempfile.name
        database.initialize(self.db_path)
        self.camera_id = database.create_camera(
            self.db_path, name="Eingang", host="192.0.2.10", onvif_port=8000, http_port=80, username="a", password="b"
        )
        self.zone_id = database.create_camera_detection_zone(
            self.db_path, self.camera_id, name="Tuer", mode="line", classes=None,
            points=[(0.2, 0.5), (0.8, 0.5)], min_dwell_seconds=10,
        )

    def tearDown(self):
        self._tempfile.close()

    def test_increment_accumulates_per_direction(self):
        database.increment_zone_crossing_count(self.db_path, self.zone_id, "in")
        database.increment_zone_crossing_count(self.db_path, self.zone_id, "in")
        database.increment_zone_crossing_count(self.db_path, self.zone_id, "out")
        counts = database.get_zone_crossing_counts(self.db_path, self.zone_id)
        self.assertEqual(counts, {"in": 2, "out": 1})

    def test_unknown_direction_is_ignored(self):
        database.increment_zone_crossing_count(self.db_path, self.zone_id, "sideways")
        counts = database.get_zone_crossing_counts(self.db_path, self.zone_id)
        self.assertEqual(counts, {"in": 0, "out": 0})

    def test_reset_clears_both_directions(self):
        database.increment_zone_crossing_count(self.db_path, self.zone_id, "in")
        database.increment_zone_crossing_count(self.db_path, self.zone_id, "out")
        database.reset_zone_crossing_counts(self.db_path, self.zone_id)
        self.assertEqual(database.get_zone_crossing_counts(self.db_path, self.zone_id), {"in": 0, "out": 0})

    def test_counts_are_deleted_when_the_zone_is_deleted(self):
        database.increment_zone_crossing_count(self.db_path, self.zone_id, "in")
        database.delete_camera_detection_zone(self.db_path, self.camera_id, self.zone_id)
        # No error, and a fresh zone re-using the same id (via a new insert) starts at zero -
        # the ON DELETE CASCADE foreign key is what's actually under test here.
        self.assertEqual(database.get_zone_crossing_counts(self.db_path, self.zone_id), {"in": 0, "out": 0})


if __name__ == "__main__":
    unittest.main()
