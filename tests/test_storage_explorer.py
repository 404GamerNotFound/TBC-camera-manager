import tempfile
import unittest
from pathlib import Path

from app.tbc import database
from app.tbc.maintenance import delete_recording_group


class StorageExplorerTests(unittest.TestCase):
    def test_usage_is_split_by_storage_and_group_delete_removes_its_files(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "tbc.sqlite3")
            database.initialize(database_path)
            camera_id = database.create_camera(
                database_path,
                name="Driveway",
                host="192.0.2.8",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            archive_id = database.create_storage_target(
                database_path,
                name="Archive",
                kind="local",
                local_path=directory,
            )
            clip_path = Path(directory) / "driveway.mp4"
            clip_path.write_bytes(b"clip")
            archive_recording_id = database.create_recording(
                database_path,
                camera_id=camera_id,
                storage_id=archive_id,
                detection_key="person",
                event_label="Person",
                storage_kind="local",
                started_at="2026-07-19T12:00:00",
            )
            database.update_recording_finished(
                database_path,
                archive_recording_id,
                status="ready",
                local_path=str(clip_path),
                size_bytes=4,
            )
            unassigned_recording_id = database.create_recording(
                database_path,
                camera_id=camera_id,
                storage_id=None,
                detection_key="person",
                event_label="Person",
                storage_kind="local",
                started_at="2026-07-19T12:01:00",
            )
            database.update_recording_finished(
                database_path,
                unassigned_recording_id,
                status="ready",
                size_bytes=8,
            )

            usage = database.list_recording_sizes_by_camera_event(database_path)
            person_rows = [row for row in usage if row["camera_id"] == camera_id and row["detection_key"] == "person"]

            self.assertEqual(len(person_rows), 2)
            self.assertEqual(next(row for row in person_rows if row["storage_id"] == archive_id)["storage_name"], "Archive")
            self.assertEqual(delete_recording_group(database_path, camera_id=camera_id, detection_key="person", storage_id=archive_id), 1)
            self.assertFalse(clip_path.exists())
            self.assertIsNone(database.get_recording(database_path, archive_recording_id))
            self.assertIsNotNone(database.get_recording(database_path, unassigned_recording_id))


if __name__ == "__main__":
    unittest.main()
