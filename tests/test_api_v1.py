import os
import tempfile
import unittest

from app.tbc import database
from app.tbc.security import generate_api_key, hash_api_key, verify_api_key

_TMP_ROOT = tempfile.mkdtemp()
os.environ.setdefault("TBC_DATABASE_PATH", os.path.join(_TMP_ROOT, "tbc.sqlite3"))
os.environ.setdefault("TBC_RECORDINGS_PATH", os.path.join(_TMP_ROOT, "recordings"))
os.environ.setdefault("TBC_LIVE_PATH", os.path.join(_TMP_ROOT, "live"))
os.environ.setdefault("TBC_CAMERA_MODULES_PATH", os.path.join(_TMP_ROOT, "camera-modules"))
os.environ.setdefault("TBC_DASHBOARD_SNAPSHOTS_PATH", os.path.join(_TMP_ROOT, "dashboard-snapshots"))
os.environ.setdefault("TBC_DETECTION_MODELS_PATH", os.path.join(_TMP_ROOT, "detection-models"))
os.environ.setdefault("TBC_SECRET_KEY", "test-secret-key-for-api-v1-tests")

from app.tbc.main import _api_auth_error  # noqa: E402  (import after env setup, see above)


class ApiKeySecurityTests(unittest.TestCase):
    def test_generate_api_key_has_expected_prefix_and_length(self):
        key = generate_api_key()
        self.assertTrue(key.startswith("tbc_"))
        self.assertGreater(len(key), 30)

    def test_generate_api_key_is_random(self):
        self.assertNotEqual(generate_api_key(), generate_api_key())

    def test_verify_api_key_accepts_matching_hash(self):
        key = generate_api_key()
        self.assertTrue(verify_api_key(key, hash_api_key(key)))

    def test_verify_api_key_rejects_wrong_key(self):
        key = generate_api_key()
        self.assertFalse(verify_api_key("wrong-key", hash_api_key(key)))

    def test_verify_api_key_rejects_empty_inputs(self):
        key = generate_api_key()
        self.assertFalse(verify_api_key("", hash_api_key(key)))
        self.assertFalse(verify_api_key(key, ""))
        self.assertFalse(verify_api_key("", ""))


class ApiConfigDatabaseTests(unittest.TestCase):
    def test_default_config_is_disabled_with_key_required(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            config = database.get_api_config(handle.name)
        self.assertEqual(config["enabled"], 0)
        self.assertEqual(config["require_api_key"], 1)
        self.assertIsNone(config["api_key_hash"])
        self.assertIsNone(config["api_key_prefix"])

    def test_update_api_config_persists_flags(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.update_api_config(handle.name, enabled=True, require_api_key=False)
            config = database.get_api_config(handle.name)
        self.assertEqual(config["enabled"], 1)
        self.assertEqual(config["require_api_key"], 0)

    def test_set_api_key_then_clear_api_key(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.set_api_key(handle.name, key_hash="deadbeef", key_prefix="tbc_AbCd1234")
            config = database.get_api_config(handle.name)
            self.assertEqual(config["api_key_hash"], "deadbeef")
            self.assertEqual(config["api_key_prefix"], "tbc_AbCd1234")

            database.clear_api_key(handle.name)
            config = database.get_api_config(handle.name)
            self.assertIsNone(config["api_key_hash"])
            self.assertIsNone(config["api_key_prefix"])

    def test_generating_new_key_replaces_previous_one(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.set_api_key(handle.name, key_hash="first-hash", key_prefix="tbc_first")
            database.set_api_key(handle.name, key_hash="second-hash", key_prefix="tbc_second")
            config = database.get_api_config(handle.name)
        self.assertEqual(config["api_key_hash"], "second-hash")
        self.assertEqual(config["api_key_prefix"], "tbc_second")


class ApiAuthGateTests(unittest.TestCase):
    def test_disabled_api_returns_404_regardless_of_key(self):
        config = {"enabled": False, "require_api_key": True, "api_key_hash": None}
        self.assertEqual(_api_auth_error(config, None, None), (404, "API ist deaktiviert"))

    def test_enabled_without_key_requirement_allows_no_credentials(self):
        config = {"enabled": True, "require_api_key": False, "api_key_hash": None}
        self.assertIsNone(_api_auth_error(config, None, None))

    def test_enabled_with_key_required_rejects_missing_key(self):
        key_hash = hash_api_key(generate_api_key())
        config = {"enabled": True, "require_api_key": True, "api_key_hash": key_hash}
        self.assertEqual(_api_auth_error(config, None, None), (401, "ungültiger oder fehlender API-Key"))

    def test_enabled_with_key_required_rejects_wrong_key(self):
        key_hash = hash_api_key(generate_api_key())
        config = {"enabled": True, "require_api_key": True, "api_key_hash": key_hash}
        error = _api_auth_error(config, "Bearer wrong-key", None)
        self.assertEqual(error, (401, "ungültiger oder fehlender API-Key"))

    def test_enabled_with_key_required_accepts_correct_bearer_token(self):
        key = generate_api_key()
        config = {"enabled": True, "require_api_key": True, "api_key_hash": hash_api_key(key)}
        self.assertIsNone(_api_auth_error(config, f"Bearer {key}", None))

    def test_enabled_with_key_required_accepts_correct_x_api_key_header(self):
        key = generate_api_key()
        config = {"enabled": True, "require_api_key": True, "api_key_hash": hash_api_key(key)}
        self.assertIsNone(_api_auth_error(config, None, key))

    def test_bearer_token_takes_precedence_over_x_api_key_header(self):
        key = generate_api_key()
        config = {"enabled": True, "require_api_key": True, "api_key_hash": hash_api_key(key)}
        error = _api_auth_error(config, "Bearer wrong-key", key)
        self.assertEqual(error, (401, "ungültiger oder fehlender API-Key"))

    def test_no_key_ever_generated_always_rejects(self):
        config = {"enabled": True, "require_api_key": True, "api_key_hash": None}
        error = _api_auth_error(config, "Bearer anything", None)
        self.assertEqual(error, (401, "ungültiger oder fehlender API-Key"))


if __name__ == "__main__":
    unittest.main()
