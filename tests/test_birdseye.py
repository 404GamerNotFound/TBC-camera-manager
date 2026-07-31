import tempfile
import unittest

from app.tbc import database


class BirdseyeSettingsTests(unittest.TestCase):
    def test_defaults_before_anything_is_saved(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            settings = database.get_birdseye_settings(handle.name)

        self.assertEqual(settings, {"enabled": False, "columns": 3, "fps": 5})

    def test_settings_round_trip(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.set_birdseye_settings(handle.name, enabled=True, columns=4, fps=10)
            settings = database.get_birdseye_settings(handle.name)

        self.assertEqual(settings, {"enabled": True, "columns": 4, "fps": 10})

    def test_settings_are_clamped_to_valid_ranges(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.set_birdseye_settings(handle.name, enabled=True, columns=99, fps=99)
            settings = database.get_birdseye_settings(handle.name)

        self.assertEqual(settings["columns"], 6)
        self.assertEqual(settings["fps"], 10)

    def test_camera_ids_default_to_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_ids = database.get_birdseye_camera_ids(handle.name)

        self.assertEqual(camera_ids, [])

    def test_camera_ids_round_trip_in_order(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            first_id = database.create_camera(
                handle.name,
                name="Einfahrt",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            second_id = database.create_camera(
                handle.name,
                name="Garten",
                host="192.0.2.11",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            database.set_birdseye_camera_ids(handle.name, [second_id, first_id])
            camera_ids = database.get_birdseye_camera_ids(handle.name)

        self.assertEqual(camera_ids, [second_id, first_id])

    def test_setting_camera_ids_replaces_the_previous_selection(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            first_id = database.create_camera(
                handle.name,
                name="Einfahrt",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            second_id = database.create_camera(
                handle.name,
                name="Garten",
                host="192.0.2.11",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            database.set_birdseye_camera_ids(handle.name, [first_id, second_id])
            database.set_birdseye_camera_ids(handle.name, [second_id])
            camera_ids = database.get_birdseye_camera_ids(handle.name)

        self.assertEqual(camera_ids, [second_id])

    def test_deleting_a_camera_removes_it_from_the_selection(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Einfahrt",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            database.set_birdseye_camera_ids(handle.name, [camera_id])
            database.delete_camera(handle.name, camera_id)
            camera_ids = database.get_birdseye_camera_ids(handle.name)

        self.assertEqual(camera_ids, [])


if __name__ == "__main__":
    unittest.main()
