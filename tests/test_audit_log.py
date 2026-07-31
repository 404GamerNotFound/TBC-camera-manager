import tempfile
import unittest

from app.tbc import database


class AuditLogTests(unittest.TestCase):
    def test_record_and_list_events(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.record_audit_event(
                handle.name,
                user_id=1,
                username="admin",
                action="auth.login_succeeded",
                ip_address="127.0.0.1",
            )
            database.record_audit_event(
                handle.name,
                user_id=1,
                username="admin",
                action="camera.created",
                target_type="camera",
                target_id=5,
                detail={"name": "Front door"},
            )

            result = database.list_audit_events(handle.name)
            self.assertEqual(result["total"], 2)
            # Newest first.
            self.assertEqual(result["events"][0]["action"], "camera.created")
            self.assertEqual(result["events"][0]["target_type"], "camera")
            self.assertEqual(result["events"][0]["target_id"], "5")
            self.assertEqual(result["events"][0]["detail"], {"name": "Front door"})
            self.assertEqual(result["events"][1]["action"], "auth.login_succeeded")
            self.assertEqual(result["events"][1]["ip_address"], "127.0.0.1")

    def test_filter_by_action(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.record_audit_event(handle.name, user_id=1, username="admin", action="auth.login_succeeded")
            database.record_audit_event(handle.name, user_id=1, username="admin", action="user.created")

            result = database.list_audit_events(handle.name, action="user.created")
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["events"][0]["action"], "user.created")

    def test_list_distinct_actions(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.record_audit_event(handle.name, user_id=1, username="admin", action="auth.login_succeeded")
            database.record_audit_event(handle.name, user_id=1, username="admin", action="auth.login_succeeded")
            database.record_audit_event(handle.name, user_id=1, username="admin", action="user.created")

            actions = database.list_distinct_audit_actions(handle.name)
            self.assertEqual(actions, ["auth.login_succeeded", "user.created"])

    def test_pagination_respects_limit_and_offset(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            for i in range(5):
                database.record_audit_event(handle.name, user_id=1, username="admin", action=f"event.{i}")

            page = database.list_audit_events(handle.name, limit=2, offset=0)
            self.assertEqual(page["total"], 5)
            self.assertEqual(len(page["events"]), 2)
            self.assertEqual(page["events"][0]["action"], "event.4")

            next_page = database.list_audit_events(handle.name, limit=2, offset=2)
            self.assertEqual(next_page["events"][0]["action"], "event.2")


class ApiTokenAuditTests(unittest.TestCase):
    def test_revoked_token_is_not_returned_by_active_lookup(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            token_id = database.create_api_token(
                handle.name,
                name="CI",
                key_hash="hash-value",
                key_prefix="tbc_prefix12",
                created_by_user_id=None,
            )
            self.assertIsNotNone(database.find_active_api_token_by_prefix(handle.name, "tbc_prefix12"))
            database.revoke_api_token(handle.name, token_id)
            self.assertIsNone(database.find_active_api_token_by_prefix(handle.name, "tbc_prefix12"))


if __name__ == "__main__":
    unittest.main()
