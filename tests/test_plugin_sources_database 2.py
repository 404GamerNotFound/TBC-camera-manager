import tempfile
import unittest

from app.tbc import database


class PluginSourceDatabaseTests(unittest.TestCase):
    def test_create_list_sync_and_delete_plugin_source(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            source_id = database.create_plugin_source(
                handle.name,
                plugin_kind="cloud",
                label="Acme Cloud Plugin",
                repo_url="https://github.com/owner/repo",
                ref="main",
                subdirectory="plugins/acme",
            )

            sources = database.list_plugin_sources(handle.name)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]["plugin_kind"], "cloud")
            self.assertIsNone(sources[0]["last_sync_status"])

            source = database.get_plugin_source(handle.name, source_id)
            self.assertEqual(source["repo_url"], "https://github.com/owner/repo")
            self.assertEqual(source["ref"], "main")

            database.update_plugin_source_sync_result(
                handle.name, source_id, status="ok", message="Installiert als 'acme'", installed_key="acme"
            )
            updated = database.get_plugin_source(handle.name, source_id)
            self.assertEqual(updated["last_sync_status"], "ok")
            self.assertEqual(updated["installed_key"], "acme")
            self.assertIsNotNone(updated["last_sync_at"])

            database.delete_plugin_source(handle.name, source_id)
            self.assertEqual(database.list_plugin_sources(handle.name), [])

    def test_defaults_apply_when_ref_and_subdirectory_omitted(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            source_id = database.create_plugin_source(
                handle.name,
                plugin_kind="camera",
                label="Acme Camera Plugin",
                repo_url="https://github.com/owner/repo",
                ref="",
                subdirectory="",
            )

            source = database.get_plugin_source(handle.name, source_id)

            self.assertEqual(source["ref"], "main")
            self.assertEqual(source["subdirectory"], "")

    def test_get_unknown_plugin_source_returns_none(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            self.assertIsNone(database.get_plugin_source(handle.name, 999))


if __name__ == "__main__":
    unittest.main()
