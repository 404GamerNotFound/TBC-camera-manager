import tempfile
import unittest

from app.tbc import database
from app.tbc.maintenance import apply_cleanup, cleanup_preview
from app.tbc.recording import _motion_is_active


class RecordingTests(unittest.TestCase):
    def test_default_storage_target_uses_configured_path(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name, "/recordings/nas")
            targets = database.list_storage_targets(handle.name)

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["kind"], "local")
        self.assertEqual(targets[0]["local_path"], "/recordings/nas")

    def test_motion_detection_accepts_single_and_channel_keys(self):
        self.assertTrue(_motion_is_active([{"key": "motion", "active": True}]))
        self.assertTrue(_motion_is_active([{"key": "ch1:motion", "active": True}]))
        self.assertFalse(_motion_is_active([{"key": "person", "active": True}]))
        self.assertFalse(_motion_is_active([{"key": "motion", "active": False}]))

    def test_retention_cleanup_preview_and_apply_by_age(self):
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
            recording_id = database.create_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=1,
                detection_key="person",
                event_label="Person",
                storage_kind="local",
                started_at="2000-06-01T12:00:00",
            )
            database.update_recording_finished(
                handle.name,
                recording_id,
                status="ready",
                size_bytes=1024,
                ended_at="2000-06-01T12:00:30",
            )
            database.create_retention_rule(
                handle.name,
                name="Personen 7 Tage",
                enabled=True,
                camera_id=camera_id,
                detection_key="person",
                max_age_days=7,
                max_size_gb=None,
            )

            preview = cleanup_preview(handle.name)
            deleted = apply_cleanup(handle.name)

            self.assertEqual([item["id"] for item in preview], [recording_id])
            self.assertEqual(deleted, 1)
            self.assertIsNone(database.get_recording(handle.name, recording_id))

    def test_retention_size_limit_keeps_newest_matching_clip(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Garage",
                host="192.0.2.20",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            older_id = database.create_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=1,
                detection_key="vehicle",
                event_label="Fahrzeug",
                storage_kind="local",
                started_at="2026-07-01T10:00:00",
            )
            newer_id = database.create_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=1,
                detection_key="vehicle",
                event_label="Fahrzeug",
                storage_kind="local",
                started_at="2026-07-02T10:00:00",
            )
            database.update_recording_finished(handle.name, older_id, status="ready", size_bytes=700)
            database.update_recording_finished(handle.name, newer_id, status="ready", size_bytes=700)
            database.create_retention_rule(
                handle.name,
                name="Fahrzeuge klein halten",
                enabled=True,
                camera_id=camera_id,
                detection_key="vehicle",
                max_age_days=None,
                max_size_gb=0.000001,
            )

            preview = cleanup_preview(handle.name)

            self.assertEqual([item["id"] for item in preview], [older_id])
            self.assertIsNotNone(database.get_recording(handle.name, newer_id))

    def test_storage_target_retention_is_included_in_cleanup_preview(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.update_storage_target(
                handle.name,
                1,
                name="Lokaler Container-Speicher",
                kind="local",
                local_path="/recordings",
                retention_days=7,
                retention_max_gb=None,
            )
            camera_id = database.create_camera(
                handle.name,
                name="Hof",
                host="192.0.2.40",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            recording_id = database.create_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=1,
                detection_key="motion",
                event_label="Bewegung",
                storage_kind="local",
                started_at="2000-01-01T12:00:00",
            )
            database.update_recording_finished(handle.name, recording_id, status="ready", size_bytes=256)

            preview = cleanup_preview(handle.name)

            self.assertEqual([item["id"] for item in preview], [recording_id])


if __name__ == "__main__":
    unittest.main()
