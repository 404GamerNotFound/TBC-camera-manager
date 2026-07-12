import tempfile
import unittest

from app.tbc import database


class CloudAccountDatabaseTests(unittest.TestCase):
    def test_create_list_test_and_delete_cloud_account(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            account_id = database.create_cloud_account(
                handle.name,
                module_key="unifi_protect",
                label="Zuhause",
                host="10.0.0.1",
                port=443,
                verify_ssl=False,
                identifier="admin",
                secret="secret",
            )

            accounts = database.list_cloud_accounts(handle.name)
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0]["label"], "Zuhause")
            self.assertIsNone(accounts[0]["last_test_status"])

            account = database.get_cloud_account(handle.name, account_id)
            self.assertEqual(account["identifier"], "admin")
            self.assertEqual(account["verify_ssl"], 0)

            database.update_cloud_account_test_result(
                handle.name, account_id, status="ok", message="Verbunden mit Zuhause NVR"
            )
            updated = database.get_cloud_account(handle.name, account_id)
            self.assertEqual(updated["last_test_status"], "ok")
            self.assertEqual(updated["last_test_message"], "Verbunden mit Zuhause NVR")
            self.assertIsNotNone(updated["last_test_at"])

            self.assertEqual(database.count_cloud_accounts_by_module(handle.name, "unifi_protect"), 1)
            self.assertEqual(database.count_cloud_accounts_by_module(handle.name, "other"), 0)

            database.delete_cloud_account(handle.name, account_id)
            self.assertEqual(database.list_cloud_accounts(handle.name), [])

    def test_get_unknown_cloud_account_returns_none(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            self.assertIsNone(database.get_cloud_account(handle.name, 999))


if __name__ == "__main__":
    unittest.main()
