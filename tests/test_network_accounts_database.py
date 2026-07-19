import tempfile
import unittest

from app.tbc import database


class NetworkAccountDatabaseTests(unittest.TestCase):
    def test_create_list_test_and_delete_network_account(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            account_id = database.create_network_account(
                handle.name,
                module_key="unifi-network",
                label="Zuhause",
                config={
                    "host": "10.0.0.1",
                    "port": 8443,
                    "site": "default",
                    "verify_ssl": False,
                    "identifier": "admin",
                    "secret": "secret",
                },
            )

            accounts = database.list_network_accounts(handle.name)
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0]["label"], "Zuhause")
            self.assertIsNone(accounts[0]["last_test_status"])

            account = database.get_network_account(handle.name, account_id)
            self.assertEqual(account["identifier"], "admin")
            self.assertEqual(account["verify_ssl"], 0)
            self.assertEqual(account["secret"], "secret")
            self.assertEqual(account["config"]["site"], "default")

            database.update_network_account_test_result(
                handle.name, account_id, status="ok", message="Connected - 4 device(s) found"
            )
            updated = database.get_network_account(handle.name, account_id)
            self.assertEqual(updated["last_test_status"], "ok")
            self.assertEqual(updated["last_test_message"], "Connected - 4 device(s) found")
            self.assertIsNotNone(updated["last_test_at"])

            self.assertEqual(database.count_network_accounts_by_module(handle.name, "unifi-network"), 1)
            self.assertEqual(database.count_network_accounts_by_module(handle.name, "other"), 0)

            database.delete_network_account(handle.name, account_id)
            self.assertEqual(database.list_network_accounts(handle.name), [])

    def test_get_unknown_network_account_returns_none(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            self.assertIsNone(database.get_network_account(handle.name, 999))

    def test_updating_configuration_preserves_unchanged_fields(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            account_id = database.create_network_account(
                handle.name,
                module_key="unifi-network",
                label="Zuhause",
                config={"host": "10.0.0.1", "identifier": "admin", "secret": "secret"},
            )

            database.update_network_account_configuration(
                handle.name,
                account_id,
                label="Büro",
                config={"host": "10.0.0.2", "identifier": "admin", "secret": "secret"},
            )

            updated = database.get_network_account(handle.name, account_id)
            self.assertEqual(updated["label"], "Büro")
            self.assertEqual(updated["host"], "10.0.0.2")
            self.assertEqual(updated["secret"], "secret")

    def test_secret_is_encrypted_at_rest(self):
        import sqlite3

        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.configure_encryption("test-secret-key")
            database.initialize(handle.name)
            database.create_network_account(
                handle.name,
                module_key="unifi-network",
                label="Zuhause",
                config={"host": "10.0.0.1", "identifier": "admin", "secret": "plaintext-password"},
            )
            with sqlite3.connect(handle.name) as connection:
                row = connection.execute("SELECT secret FROM network_accounts").fetchone()
            self.assertNotEqual(row[0], "plaintext-password")

    def test_custom_named_password_field_is_encrypted_at_rest(self):
        # Mirrors the cloud_accounts fix: a module using a custom field name
        # (not literally "secret") needs sensitive_keys to get encrypted.
        import sqlite3

        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.configure_encryption("test-secret-key")
            database.initialize(handle.name)
            account_id = database.create_network_account(
                handle.name,
                module_key="example-network",
                label="Example",
                config={"host": "10.0.0.1", "api_key": "plaintext-api-key"},
                sensitive_keys=("api_key",),
            )
            with sqlite3.connect(handle.name) as connection:
                row = connection.execute("SELECT config_json FROM network_accounts").fetchone()
            self.assertNotIn("plaintext-api-key", row[0])

            account = database.get_network_account(handle.name, account_id)
            self.assertEqual(account["api_key"], "plaintext-api-key")


class CameraNetworkMappingTests(unittest.TestCase):
    def test_set_and_clear_camera_network_mapping(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            account_id = database.create_network_account(
                handle.name,
                module_key="unifi-network",
                label="Zuhause",
                config={"host": "10.0.0.1", "identifier": "admin", "secret": "secret"},
            )
            camera_id = database.create_camera(
                handle.name,
                name="Front Door",
                host="192.168.1.50",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )

            database.set_camera_network_mapping(
                handle.name, camera_id, network_account_id=account_id, mac="AA:BB:CC:DD:EE:FF"
            )
            camera = database.get_camera(handle.name, camera_id)
            self.assertEqual(camera["network_account_id"], account_id)
            self.assertEqual(camera["network_device_mac"], "aa:bb:cc:dd:ee:ff")

            database.clear_camera_network_mapping(handle.name, camera_id)
            camera = database.get_camera(handle.name, camera_id)
            self.assertIsNone(camera["network_account_id"])
            self.assertIsNone(camera["network_device_mac"])

    def test_deleting_network_account_clears_camera_mapping(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            account_id = database.create_network_account(
                handle.name,
                module_key="unifi-network",
                label="Zuhause",
                config={"host": "10.0.0.1", "identifier": "admin", "secret": "secret"},
            )
            camera_id = database.create_camera(
                handle.name,
                name="Front Door",
                host="192.168.1.50",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            database.set_camera_network_mapping(
                handle.name, camera_id, network_account_id=account_id, mac="aa:bb:cc:dd:ee:ff"
            )

            database.delete_network_account(handle.name, account_id)

            camera = database.get_camera(handle.name, camera_id)
            self.assertIsNone(camera["network_account_id"])
            self.assertIsNone(camera["network_device_mac"])


class NetworkDeviceStatusAndEventsTests(unittest.TestCase):
    def _camera_id(self, db_path: str) -> int:
        return database.create_camera(
            db_path, name="Front Door", host="192.168.1.50", onvif_port=8000, http_port=80,
            username="admin", password="secret",
        )

    def test_first_upsert_records_status_and_one_event(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = self._camera_id(handle.name)

            database.upsert_network_device_status(
                handle.name, camera_id, online=True, connection_type="wired",
                uplink_name="Schuppen PoE", signal_dbm=None,
            )

            status = database.get_network_device_status(handle.name, camera_id)
            self.assertTrue(status["online"])
            self.assertEqual(status["uplink_name"], "Schuppen PoE")

            events = database.list_network_device_events(handle.name, camera_id)
            self.assertEqual(len(events), 1)
            self.assertIsNone(events[0]["previous_online"])
            self.assertTrue(events[0]["online"])

    def test_repeated_unchanged_state_does_not_add_events(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = self._camera_id(handle.name)

            for _ in range(3):
                database.upsert_network_device_status(
                    handle.name, camera_id, online=True, connection_type="wired",
                    uplink_name="Schuppen PoE", signal_dbm=-40,
                )

            events = database.list_network_device_events(handle.name, camera_id)
            self.assertEqual(len(events), 1)

    def test_going_offline_and_reconnecting_elsewhere_each_add_an_event(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = self._camera_id(handle.name)

            database.upsert_network_device_status(
                handle.name, camera_id, online=True, connection_type="wired",
                uplink_name="Schuppen PoE", signal_dbm=None,
            )
            database.upsert_network_device_status(
                handle.name, camera_id, online=False, connection_type=None,
                uplink_name=None, signal_dbm=None,
            )
            database.upsert_network_device_status(
                handle.name, camera_id, online=True, connection_type="wifi",
                uplink_name="Schuppen - U7 Long-Range", signal_dbm=-62,
            )

            status = database.get_network_device_status(handle.name, camera_id)
            self.assertEqual(status["uplink_name"], "Schuppen - U7 Long-Range")

            events = database.list_network_device_events(handle.name, camera_id)
            self.assertEqual(len(events), 3)
            # Most recent first.
            self.assertEqual(events[0]["uplink_name"], "Schuppen - U7 Long-Range")
            self.assertFalse(events[1]["online"])
            self.assertTrue(events[1]["previous_online"])


if __name__ == "__main__":
    unittest.main()
