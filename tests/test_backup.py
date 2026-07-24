import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.tbc import backup, database


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.secret_key = "test-secret-key"
        self.db_path = str(self.tmp_dir / "tbc.sqlite3")
        database.configure_encryption(self.secret_key)
        database.initialize(self.db_path)
        database.create_user(self.db_path, username="admin", password="hunter2", role="admin")
        database.create_camera(
            self.db_path,
            name="Front door",
            host="192.0.2.10",
            onvif_port=8000,
            http_port=80,
            username="admin",
            password="camera-secret",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_restore_recreates_users_and_cameras(self):
        archive = backup.create_backup(self.db_path, self.secret_key)
        restore_path = str(self.tmp_dir / "restored.sqlite3")

        backup.restore_backup(archive, restore_path, self.secret_key)

        users = database.list_users(restore_path)
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["username"], "admin")
        cameras = database.list_cameras(restore_path)
        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0]["name"], "Front door")
        # The camera password round-trips through the encrypted backup and
        # decrypts correctly with the same key on the restored database.
        self.assertEqual(cameras[0]["password"], "camera-secret")

    def test_restoring_over_existing_database_keeps_a_backup_copy(self):
        archive = backup.create_backup(self.db_path, self.secret_key)
        backup.restore_backup(archive, self.db_path, self.secret_key)
        self.assertTrue(Path(self.db_path + ".bak").exists())

    def test_restore_with_wrong_key_raises_backup_error(self):
        archive = backup.create_backup(self.db_path, self.secret_key)
        restore_path = str(self.tmp_dir / "restored.sqlite3")
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(archive, restore_path, "a-different-key")

    def test_restore_rejects_a_non_backup_file(self):
        restore_path = str(self.tmp_dir / "restored.sqlite3")
        garbage = b"not a real backup archive"
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(garbage, restore_path, self.secret_key)

    def test_local_backup_is_saved_with_versioned_timestamp_name(self):
        expected_name = f"TBC_v{backup.__version__}_2026-07-21-09-49-28.tbcbackup"
        self.assertEqual(
            backup.backup_filename(datetime(2026, 7, 21, 9, 49, 28, tzinfo=timezone.utc)),
            expected_name,
        )

        backups_path = self.tmp_dir / "backups"
        saved_backup = backup.create_backup_file(self.db_path, self.secret_key, str(backups_path))

        self.assertTrue(saved_backup.is_file())
        self.assertTrue(saved_backup.name.startswith(f"TBC_v{backup.__version__}_"))
        self.assertEqual(saved_backup.suffix, ".tbcbackup")
        self.assertEqual(backup.get_backup_file(str(backups_path), saved_backup.name), saved_backup)
        self.assertIsNone(backup.get_backup_file(str(backups_path), "../tbc.sqlite3"))
        self.assertEqual(backup.list_backup_files(str(backups_path))[0]["filename"], saved_backup.name)

    def test_database_runs_in_wal_mode_with_busy_timeout(self):
        import sqlite3

        with database.connect(self.db_path) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
        # WAL survives as a database property for plain sqlite3 connections too
        # (e.g. the backup API's own connections).
        raw = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(raw.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        finally:
            raw.close()

    def test_restore_over_wal_database_drops_stale_sidecar_files(self):
        import sqlite3

        archive = backup.create_backup(self.db_path, self.secret_key)
        # SQLite deletes the -wal sidecar when the *last* connection closes, so
        # keep one open for the whole scenario - exactly the state a live server
        # is in when an admin restores a backup - and leave a write
        # un-checkpointed in the WAL.
        holder = sqlite3.connect(self.db_path)
        self.addCleanup(holder.close)
        holder.execute("SELECT COUNT(*) FROM users").fetchone()
        with database.connect(self.db_path) as db:
            db.execute("UPDATE users SET username = 'renamed-after-backup'")
        self.assertTrue(Path(self.db_path + "-wal").exists())

        backup.restore_backup(archive, self.db_path, self.secret_key)

        self.assertFalse(Path(self.db_path + "-wal").exists())
        self.assertFalse(Path(self.db_path + "-shm").exists())
        # The restored database reflects the backup, not the leftover WAL...
        self.assertEqual(database.list_users(self.db_path)[0]["username"], "admin")
        # ...and the .bak safety copy includes the un-checkpointed rename, which
        # a plain file copy of the main database file would have lost.
        self.assertEqual(database.list_users(self.db_path + ".bak")[0]["username"], "renamed-after-backup")

    def test_schedule_configuration_and_due_calculation(self):
        database.update_backup_schedule(
            self.db_path,
            enabled=True,
            interval_hours=12,
            retain_count=10,
            storage_id=None,
        )
        schedule = database.get_backup_schedule(self.db_path)
        self.assertTrue(schedule["enabled"])
        self.assertEqual(schedule["interval_hours"], 12)
        self.assertEqual(schedule["retain_count"], 10)
        self.assertTrue(backup.schedule_is_due(schedule))

        database.record_backup_schedule_run(self.db_path, status="success", message="done")
        schedule = database.get_backup_schedule(self.db_path)
        self.assertFalse(backup.schedule_is_due(schedule))
        self.assertTrue(
            backup.schedule_is_due(
                schedule,
                now=datetime.now(timezone.utc) + timedelta(hours=13),
            )
        )

    def test_scheduled_backup_copies_to_local_target_and_applies_retention(self):
        backups_path = self.tmp_dir / "backups"
        external_path = self.tmp_dir / "external"
        result = backup.run_scheduled_backup(
            self.db_path,
            self.secret_key,
            str(backups_path),
            retain_count=1,
            storage_target={"kind": "local", "local_path": str(external_path)},
        )

        self.assertTrue((backups_path / result["filename"]).is_file())
        self.assertTrue((external_path / "tbc-backups" / result["filename"]).is_file())
        self.assertEqual(result["external_removed"], 0)

    def test_prune_backup_files_keeps_the_newest_archives(self):
        backups_path = self.tmp_dir / "backups"
        backups_path.mkdir()
        for index in range(3):
            archive = backups_path / f"TBC_vtest_2026-07-2{index}-09-00-00.tbcbackup"
            archive.write_bytes(b"encrypted backup")
            archive.touch()
            # Avoid filesystem timestamp granularity affecting the order.
            import os

            os.utime(archive, (1_000 + index, 1_000 + index))

        self.assertEqual(backup.prune_backup_files(str(backups_path), 2), 1)
        self.assertEqual(len(backup.list_backup_files(str(backups_path))), 2)


if __name__ == "__main__":
    unittest.main()
