import tempfile
import unittest

from app.tbc import database


class AccessControlTests(unittest.TestCase):
    def test_viewer_only_sees_assigned_cameras(self):
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
            database.create_camera(
                handle.name,
                name="Garten",
                host="192.0.2.11",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            user_id = database.create_user(handle.name, username="viewer", password="secret", role="viewer")
            database.set_user_camera_access(handle.name, user_id, [first_id])
            cameras = database.list_cameras_for_user(handle.name, user_id, "viewer")

        self.assertEqual([camera["name"] for camera in cameras], ["Einfahrt"])

    def test_recording_triggers_are_replaced(self):
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
            database.update_camera_recording_settings(
                handle.name,
                camera_id,
                recording_enabled=True,
                recording_duration_seconds=30,
                recording_pre_seconds=5,
                recording_post_seconds=10,
                recording_cooldown_seconds=90,
                snapshot_enabled=True,
                recording_storage_id=None,
                trigger_keys=["person", "vehicle"],
            )
            triggers = database.list_camera_recording_triggers(handle.name, camera_id)

        self.assertEqual(triggers, ["person", "vehicle"])


if __name__ == "__main__":
    unittest.main()

