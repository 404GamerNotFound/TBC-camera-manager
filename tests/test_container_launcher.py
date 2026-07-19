import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.tbc import container_launcher


class ContainerLauncherTests(unittest.TestCase):
    def test_missing_options_mean_standalone_container(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(
                container_launcher.load_home_assistant_options(Path(directory) / "missing.json")
            )

    def test_options_are_loaded_as_object(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text(json.dumps({"admin_username": "admin"}), encoding="utf-8")
            self.assertEqual(
                container_launcher.load_home_assistant_options(path),
                {"admin_username": "admin"},
            )

    def test_persistent_secret_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            first = container_launcher.persistent_secret(path)
            second = container_launcher.persistent_secret(path)
            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first), 48)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_home_assistant_options_map_to_environment(self):
        options = {
            "admin_username": "ha-admin",
            "admin_password": "a-secret-password",
            "poll_interval_seconds": 30,
            "dashboard_snapshot_interval_seconds": 120,
            "public_base_url": "https://camera.example.test",
        }
        with patch.dict(os.environ, {}, clear=True), patch.object(
            container_launcher, "persistent_secret", return_value="stable-secret"
        ):
            container_launcher.configure_home_assistant(options)
            self.assertEqual(os.environ["TBC_ADMIN_USERNAME"], "ha-admin")
            self.assertEqual(os.environ["TBC_SECRET_KEY"], "stable-secret")
            self.assertEqual(
                os.environ["TBC_RECORDINGS_PATH"], "/recordings/tbc-camera-manager"
            )
            self.assertEqual(os.environ["TBC_PLUGIN_SITE_PACKAGES_PATH"], "/data/plugin-site-packages")
            self.assertEqual(os.environ["TBC_POLL_INTERVAL_SECONDS"], "30")

    def test_home_assistant_password_is_required(self):
        with self.assertRaisesRegex(RuntimeError, "admin_password"):
            container_launcher.configure_home_assistant({"admin_username": "admin"})


if __name__ == "__main__":
    unittest.main()
