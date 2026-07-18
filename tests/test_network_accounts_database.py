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


if __name__ == "__main__":
    unittest.main()
