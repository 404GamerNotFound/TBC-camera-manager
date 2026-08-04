import tempfile
import unittest
from pathlib import Path

from app.tbc import database


class WebdavStorageTargetTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "tbc.sqlite3")
        database.configure_encryption("test-secret-key")
        database.initialize(self.db_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_and_get_round_trips_webdav_fields(self):
        storage_id = database.create_storage_target(
            self.db_path,
            name="Nextcloud",
            kind="webdav",
            webdav_url="https://cloud.example.invalid/remote.php/dav/files/user/tbc-recordings",
            webdav_username="tbc",
            webdav_password="s3cret",
        )
        target = database.get_storage_target(self.db_path, storage_id)
        self.assertEqual(target["kind"], "webdav")
        self.assertEqual(target["webdav_url"], "https://cloud.example.invalid/remote.php/dav/files/user/tbc-recordings")
        self.assertEqual(target["webdav_username"], "tbc")
        self.assertEqual(target["webdav_password"], "s3cret")

    def test_password_is_encrypted_at_rest(self):
        storage_id = database.create_storage_target(
            self.db_path,
            name="Nextcloud",
            kind="webdav",
            webdav_url="https://cloud.example.invalid/dav",
            webdav_username="tbc",
            webdav_password="s3cret",
        )
        with database.connect(self.db_path) as db:
            raw = db.execute(
                "SELECT webdav_password FROM storage_targets WHERE id = ?", (storage_id,)
            ).fetchone()["webdav_password"]
        self.assertNotEqual(raw, "s3cret")
        self.assertTrue(database.is_encrypted_secret(raw))

    def test_update_replaces_webdav_fields(self):
        storage_id = database.create_storage_target(
            self.db_path, name="Nextcloud", kind="webdav", webdav_url="https://old.invalid/dav"
        )
        database.update_storage_target(
            self.db_path,
            storage_id,
            name="Nextcloud",
            kind="webdav",
            webdav_url="https://new.invalid/dav",
            webdav_username="new-user",
            webdav_password="new-secret",
        )
        target = database.get_storage_target(self.db_path, storage_id)
        self.assertEqual(target["webdav_url"], "https://new.invalid/dav")
        self.assertEqual(target["webdav_username"], "new-user")
        self.assertEqual(target["webdav_password"], "new-secret")

    def test_list_storage_targets_decrypts_webdav_password(self):
        database.create_storage_target(
            self.db_path, name="Nextcloud", kind="webdav", webdav_url="https://x.invalid/dav", webdav_password="s3cret"
        )
        targets = database.list_storage_targets(self.db_path)
        nextcloud = next(target for target in targets if target["name"] == "Nextcloud")
        self.assertEqual(nextcloud["webdav_password"], "s3cret")


class NotificationSenderIdTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "tbc.sqlite3")
        database.initialize(self.db_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_signal_channel_round_trips_sender_id(self):
        channel_id = database.create_notification_channel(
            self.db_path,
            name="Signal",
            kind="signal",
            enabled=True,
            include_snapshot=False,
            url="http://signal-cli-rest-api:8080",
            sender_id="+491234567890",
            chat_id="+499876543210",
        )
        channel = database.get_notification_channel(self.db_path, channel_id)
        self.assertEqual(channel["sender_id"], "+491234567890")
        self.assertEqual(channel["chat_id"], "+499876543210")


if __name__ == "__main__":
    unittest.main()
