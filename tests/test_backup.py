import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
