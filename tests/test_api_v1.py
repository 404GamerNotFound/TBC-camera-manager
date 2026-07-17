import tempfile
import unittest

from app.tbc import database
from app.tbc.api_common import (
    api_auth_error,
    camera_public_dict,
    recording_public_dict,
    storage_public_dict,
)
from app.tbc.security import generate_api_key, hash_api_key, verify_api_key


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

    def test_create_api_token_then_revoke(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            token_id = database.create_api_token(
                handle.name, name="CI", key_hash="deadbeef", key_prefix="tbc_AbCd1234", created_by_user_id=None
            )
            tokens = database.list_api_tokens(handle.name)
            self.assertEqual(len(tokens), 1)
            self.assertEqual(tokens[0]["token_hash"], "deadbeef")
            self.assertEqual(tokens[0]["token_prefix"], "tbc_AbCd1234")
            self.assertIsNone(tokens[0]["revoked_at"])
            self.assertFalse(tokens[0]["can_control"])

            database.revoke_api_token(handle.name, token_id)
            found = database.find_active_api_token_by_prefix(handle.name, "tbc_AbCd1234")
            self.assertIsNone(found)

    def test_create_api_token_with_control_scope(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.create_api_token(
                handle.name,
                name="Home Assistant",
                key_hash="hash",
                key_prefix="tbc_hassio1234",
                created_by_user_id=None,
                can_control=True,
            )
            found = database.find_active_api_token_by_prefix(handle.name, "tbc_hassio1234")
            self.assertTrue(found["can_control"])

    def test_multiple_tokens_coexist(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.create_api_token(
                handle.name, name="A", key_hash="first-hash", key_prefix="tbc_first", created_by_user_id=None
            )
            database.create_api_token(
                handle.name, name="B", key_hash="second-hash", key_prefix="tbc_second", created_by_user_id=None
            )
            tokens = database.list_api_tokens(handle.name)
        self.assertEqual(len(tokens), 2)
        self.assertEqual({t["token_hash"] for t in tokens}, {"first-hash", "second-hash"})


def _find_token(token_hash: str, prefix: str):
    def _finder(candidate_prefix: str):
        if candidate_prefix == prefix:
            return {"id": 1, "token_hash": token_hash}
        return None

    return _finder


class ApiAuthGateTests(unittest.TestCase):
    def test_disabled_api_returns_404_regardless_of_key(self):
        config = {"enabled": False, "require_api_key": True}
        self.assertEqual(
            api_auth_error(config, None, None, find_token=lambda prefix: None), (404, "API ist deaktiviert")
        )

    def test_enabled_without_key_requirement_allows_no_credentials(self):
        config = {"enabled": True, "require_api_key": False}
        self.assertIsNone(api_auth_error(config, None, None, find_token=lambda prefix: None))

    def test_enabled_with_key_required_rejects_missing_key(self):
        config = {"enabled": True, "require_api_key": True}
        self.assertEqual(
            api_auth_error(config, None, None, find_token=lambda prefix: None),
            (401, "invalid or missing API key"),
        )

    def test_enabled_with_key_required_rejects_wrong_key(self):
        key = generate_api_key()
        config = {"enabled": True, "require_api_key": True}
        error = api_auth_error(config, "Bearer wrong-key-wrong-key", None, find_token=_find_token(hash_api_key(key), "wrong-key-wr"))
        self.assertEqual(error, (401, "invalid or missing API key"))

    def test_enabled_with_key_required_accepts_correct_bearer_token(self):
        key = generate_api_key()
        config = {"enabled": True, "require_api_key": True}
        self.assertIsNone(
            api_auth_error(config, f"Bearer {key}", None, find_token=_find_token(hash_api_key(key), key[:12]))
        )

    def test_enabled_with_key_required_accepts_correct_x_api_key_header(self):
        key = generate_api_key()
        config = {"enabled": True, "require_api_key": True}
        self.assertIsNone(
            api_auth_error(config, None, key, find_token=_find_token(hash_api_key(key), key[:12]))
        )

    def test_bearer_token_takes_precedence_over_x_api_key_header(self):
        key = generate_api_key()
        other = generate_api_key()
        config = {"enabled": True, "require_api_key": True}
        error = api_auth_error(
            config, "Bearer wrong-key-wrong-key", other, find_token=_find_token(hash_api_key(key), key[:12])
        )
        self.assertEqual(error, (401, "invalid or missing API key"))

    def test_no_matching_token_always_rejects(self):
        config = {"enabled": True, "require_api_key": True}
        error = api_auth_error(config, "Bearer anything-anything", None, find_token=lambda prefix: None)
        self.assertEqual(error, (401, "invalid or missing API key"))

    def test_on_success_callback_invoked_with_matched_token(self):
        key = generate_api_key()
        config = {"enabled": True, "require_api_key": True}
        seen = []
        error = api_auth_error(
            config,
            f"Bearer {key}",
            None,
            find_token=_find_token(hash_api_key(key), key[:12]),
            on_success=seen.append,
        )
        self.assertIsNone(error)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["id"], 1)


class CameraPublicDictTests(unittest.TestCase):
    def test_unknown_module_key_yields_empty_capabilities(self):
        camera = {
            "id": 1,
            "name": "Einfahrt",
            "module_key": "does-not-exist",
            "enabled": 1,
            "stream_uri": None,
        }
        result = camera_public_dict(camera)
        self.assertIsNone(result["module_label"])
        self.assertEqual(result["capabilities"], [])
        self.assertEqual(result["snapshot_url"], "/api/v1/cameras/1/snapshot")

    def test_stream_uri_credentials_are_redacted(self):
        camera = {
            "id": 2,
            "name": "Garten",
            "module_key": "rtsp_only",
            "enabled": 1,
            "stream_uri": "rtsp://admin:secret@192.0.2.10:554/stream1",
        }
        result = camera_public_dict(camera)
        self.assertNotIn("secret", result["stream_uri"])

    def test_missing_stream_uri_stays_none(self):
        camera = {"id": 3, "name": "Flur", "module_key": None, "enabled": 0}
        result = camera_public_dict(camera)
        self.assertIsNone(result["stream_uri"])
        self.assertFalse(result["enabled"])


class RecordingPublicDictTests(unittest.TestCase):
    def test_snapshot_url_present_when_local_snapshot_exists(self):
        recording = {
            "id": 5,
            "camera_id": 1,
            "detection_key": "ai_person",
            "event_label": "Person",
            "status": "ready",
            "started_at": "2026-01-01T08:00:00",
            "snapshot_path": "/data/recordings/5.jpg",
        }
        result = recording_public_dict(recording)
        self.assertEqual(result["snapshot_url"], "/api/v1/recordings/5/snapshot")
        self.assertEqual(result["media_url"], "/api/v1/recordings/5/media")

    def test_snapshot_url_none_without_any_snapshot(self):
        recording = {
            "id": 6,
            "camera_id": 1,
            "detection_key": "motion",
            "event_label": "Bewegung",
            "status": "ready",
            "started_at": "2026-01-01T08:00:00",
        }
        result = recording_public_dict(recording)
        self.assertIsNone(result["snapshot_url"])

    def test_remote_snapshot_key_also_counts(self):
        recording = {
            "id": 7,
            "camera_id": 1,
            "detection_key": "motion",
            "event_label": "Bewegung",
            "status": "ready",
            "started_at": "2026-01-01T08:00:00",
            "snapshot_remote_key": "recordings/7.jpg",
        }
        result = recording_public_dict(recording)
        self.assertEqual(result["snapshot_url"], "/api/v1/recordings/7/snapshot")


class StoragePublicDictTests(unittest.TestCase):
    def test_s3_secrets_are_never_included(self):
        target = {
            "id": 1,
            "name": "Cloud",
            "kind": "s3",
            "local_path": None,
            "s3_bucket": "my-bucket",
            "s3_region": "eu-central-1",
            "s3_access_key_id": "AKIA...",
            "s3_secret_access_key": "super-secret",
            "retention_days": 30,
            "retention_max_gb": 100,
        }
        result = storage_public_dict(target)
        self.assertNotIn("s3_access_key_id", result)
        self.assertNotIn("s3_secret_access_key", result)
        self.assertEqual(result["s3_bucket"], "my-bucket")


if __name__ == "__main__":
    unittest.main()
