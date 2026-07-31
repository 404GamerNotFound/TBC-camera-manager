import sqlite3
import tempfile
import unittest

from app.tbc import database


class RecognitionEventFilterTests(unittest.TestCase):
    def setUp(self):
        self._tempfile = tempfile.NamedTemporaryFile(suffix=".sqlite3")
        self.db_path = self._tempfile.name
        database.initialize(self.db_path)

        self.camera_a = database.create_camera(
            self.db_path, name="Front door", host="192.0.2.10",
            onvif_port=8000, http_port=80, username="admin", password="secret",
        )
        self.camera_b = database.create_camera(
            self.db_path, name="Garage", host="192.0.2.11",
            onvif_port=8000, http_port=80, username="admin", password="secret",
        )
        self.face_id = database.create_known_face(self.db_path, name="Alex", embedding="[]")
        self.plate_id = database.create_known_plate(self.db_path, plate_text="B-TB 1234", label="Own car")

        # event_a: camera_a, face match, old date
        self.event_a = database.create_recognition_event(
            self.db_path, recording_id=None, camera_id=self.camera_a, kind="face",
            matched_face_id=self.face_id, label="Alex", confidence=0.9,
        )
        # event_b: camera_b, plate match, recent date
        self.event_b = database.create_recognition_event(
            self.db_path, recording_id=None, camera_id=self.camera_b, kind="plate",
            matched_plate_id=self.plate_id, label="B-TB 1234", confidence=0.8,
        )
        # event_c: camera_a, unmatched face
        self.event_c = database.create_recognition_event(
            self.db_path, recording_id=None, camera_id=self.camera_a, kind="face",
            label="unknown", confidence=0.4,
        )
        # event_d: camera_b, unmatched plate
        self.event_d = database.create_recognition_event(
            self.db_path, recording_id=None, camera_id=self.camera_b, kind="plate",
            label="unknown", confidence=0.3,
        )

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE recognition_events SET created_at = ? WHERE id = ?",
                ("2026-01-01 08:00:00", self.event_a),
            )
            connection.execute(
                "UPDATE recognition_events SET created_at = ? WHERE id = ?",
                ("2026-06-15 08:00:00", self.event_b),
            )
            connection.execute(
                "UPDATE recognition_events SET created_at = ? WHERE id = ?",
                ("2026-06-15 09:00:00", self.event_c),
            )
            connection.execute(
                "UPDATE recognition_events SET created_at = ? WHERE id = ?",
                ("2026-06-16 09:00:00", self.event_d),
            )

    def tearDown(self):
        self._tempfile.close()

    def test_camera_filter(self):
        events = database.list_recognition_events(self.db_path, camera_id=self.camera_a)
        self.assertEqual({e["id"] for e in events}, {self.event_a, self.event_c})

    def test_date_range_filter(self):
        events = database.list_recognition_events(
            self.db_path, date_from="2026-06-15 00:00:00", date_to="2026-06-15 23:59:59"
        )
        self.assertEqual({e["id"] for e in events}, {self.event_b, self.event_c})

    def test_kind_filter(self):
        events = database.list_recognition_events(self.db_path, kind="plate")
        self.assertEqual({e["id"] for e in events}, {self.event_b, self.event_d})

    def test_identity_face_filter(self):
        events = database.list_recognition_events(self.db_path, matched_face_id=self.face_id)
        self.assertEqual({e["id"] for e in events}, {self.event_a})

    def test_identity_plate_filter(self):
        events = database.list_recognition_events(self.db_path, matched_plate_id=self.plate_id)
        self.assertEqual({e["id"] for e in events}, {self.event_b})

    def test_identity_unknown_filter_is_kind_mixed(self):
        events = database.list_recognition_events(self.db_path, unknown_only=True)
        self.assertEqual({e["id"] for e in events}, {self.event_c, self.event_d})

    def test_identity_unknown_filter_combines_with_kind(self):
        events = database.list_recognition_events(self.db_path, unknown_only=True, kind="face")
        self.assertEqual({e["id"] for e in events}, {self.event_c})

    def test_pagination_math(self):
        total = database.count_recognition_events(self.db_path)
        self.assertEqual(total, 4)
        page_one = database.list_recognition_events(self.db_path, limit=2, offset=0)
        page_two = database.list_recognition_events(self.db_path, limit=2, offset=2)
        self.assertEqual(len(page_one), 2)
        self.assertEqual(len(page_two), 2)
        self.assertEqual(
            {e["id"] for e in page_one} | {e["id"] for e in page_two},
            {self.event_a, self.event_b, self.event_c, self.event_d},
        )

    def test_count_matches_filtered_list(self):
        total = database.count_recognition_events(self.db_path, camera_id=self.camera_b)
        self.assertEqual(total, 2)

    def test_get_recognition_event_returns_row(self):
        event = database.get_recognition_event(self.db_path, self.event_a)
        self.assertIsNotNone(event)
        self.assertEqual(event["camera_name"], "Front door")
        self.assertEqual(event["label"], "Alex")

    def test_get_recognition_event_missing_returns_none(self):
        self.assertIsNone(database.get_recognition_event(self.db_path, 999999))


if __name__ == "__main__":
    unittest.main()
