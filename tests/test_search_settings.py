import tempfile
import unittest

from app.tbc import database


class SearchSettingsTests(unittest.TestCase):
    def setUp(self):
        self._tempfile = tempfile.NamedTemporaryFile(suffix=".sqlite3")
        self.db_path = self._tempfile.name
        database.initialize(self.db_path)

    def tearDown(self):
        self._tempfile.close()

    def test_defaults_are_disabled_with_the_documented_default_model(self):
        settings = database.get_search_settings(self.db_path)
        self.assertEqual(settings["enabled"], 0)
        self.assertEqual(settings["model_name"], "ViT-B-32__openai")

    def test_update_persists_enabled_flag_and_model_name(self):
        database.update_search_settings(self.db_path, enabled=True, model_name="RN50__openai")
        settings = database.get_search_settings(self.db_path)
        self.assertEqual(settings["enabled"], 1)
        self.assertEqual(settings["model_name"], "RN50__openai")


class RecordingEmbeddingsTests(unittest.TestCase):
    def setUp(self):
        self._tempfile = tempfile.NamedTemporaryFile(suffix=".sqlite3")
        self.db_path = self._tempfile.name
        database.initialize(self.db_path)
        self.camera_a = database.create_camera(
            self.db_path, name="A", host="192.0.2.10", onvif_port=8000, http_port=80, username="a", password="b"
        )
        self.camera_b = database.create_camera(
            self.db_path, name="B", host="192.0.2.11", onvif_port=8000, http_port=80, username="a", password="b"
        )
        self.recording_a = database.create_recording(
            self.db_path,
            camera_id=self.camera_a,
            storage_id=1,
            detection_key="ai_vehicle",
            event_label="A",
            storage_kind="local",
            started_at="2000-01-01T00:00:00",
        )
        self.recording_b = database.create_recording(
            self.db_path,
            camera_id=self.camera_b,
            storage_id=1,
            detection_key="ai_vehicle",
            event_label="B",
            storage_kind="local",
            started_at="2000-01-02T00:00:00",
        )

    def tearDown(self):
        self._tempfile.close()

    def test_upsert_then_list_round_trips_the_embedding(self):
        database.upsert_recording_embedding(self.db_path, self.recording_a, "m", [0.1, 0.2, 0.3])
        rows = database.list_recording_embeddings(self.db_path, model_name="m")
        self.assertEqual(rows, [{"recording_id": self.recording_a, "embedding": [0.1, 0.2, 0.3]}])

    def test_upsert_overwrites_an_existing_embedding_for_the_same_recording(self):
        database.upsert_recording_embedding(self.db_path, self.recording_a, "m", [0.1, 0.2])
        database.upsert_recording_embedding(self.db_path, self.recording_a, "m", [0.9, 0.9])
        rows = database.list_recording_embeddings(self.db_path, model_name="m")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["embedding"], [0.9, 0.9])

    def test_list_only_returns_embeddings_for_the_requested_model_name(self):
        database.upsert_recording_embedding(self.db_path, self.recording_a, "model-1", [1.0])
        database.upsert_recording_embedding(self.db_path, self.recording_b, "model-2", [2.0])
        rows = database.list_recording_embeddings(self.db_path, model_name="model-1")
        self.assertEqual(rows, [{"recording_id": self.recording_a, "embedding": [1.0]}])

    def test_switching_model_name_replaces_a_recording_s_previous_embedding(self):
        # recording_embeddings keeps one active slot per recording (whichever model computed
        # it most recently) rather than a full history - switching the configured model is
        # expected to require a fresh backfill rather than keep stale multi-model rows around.
        database.upsert_recording_embedding(self.db_path, self.recording_a, "model-1", [1.0])
        database.upsert_recording_embedding(self.db_path, self.recording_a, "model-2", [2.0])
        self.assertEqual(database.list_recording_embeddings(self.db_path, model_name="model-1"), [])
        rows = database.list_recording_embeddings(self.db_path, model_name="model-2")
        self.assertEqual(rows, [{"recording_id": self.recording_a, "embedding": [2.0]}])

    def test_list_filters_by_camera_id(self):
        database.upsert_recording_embedding(self.db_path, self.recording_a, "m", [1.0])
        database.upsert_recording_embedding(self.db_path, self.recording_b, "m", [2.0])
        rows = database.list_recording_embeddings(self.db_path, model_name="m", camera_id=self.camera_a)
        self.assertEqual([row["recording_id"] for row in rows], [self.recording_a])

    def test_non_admin_only_sees_embeddings_for_cameras_they_have_access_to(self):
        database.upsert_recording_embedding(self.db_path, self.recording_a, "m", [1.0])
        database.upsert_recording_embedding(self.db_path, self.recording_b, "m", [2.0])
        user_id = database.create_user(self.db_path, username="viewer", password="x", role="viewer")
        database.set_user_camera_access(self.db_path, user_id, [self.camera_a])

        admin_rows = database.list_recording_embeddings(self.db_path, model_name="m", role="admin")
        viewer_rows = database.list_recording_embeddings(self.db_path, model_name="m", user_id=user_id, role="viewer")

        self.assertEqual({row["recording_id"] for row in admin_rows}, {self.recording_a, self.recording_b})
        self.assertEqual({row["recording_id"] for row in viewer_rows}, {self.recording_a})

    def test_missing_embedding_helpers_track_ready_recordings_with_a_snapshot(self):
        database.update_recording_finished(self.db_path, self.recording_a, status="ready", snapshot_path="/tmp/a.jpg")
        database.update_recording_finished(self.db_path, self.recording_b, status="ready", snapshot_path="/tmp/b.jpg")

        self.assertEqual(database.count_recordings_missing_embedding(self.db_path, "m"), 2)
        missing = database.list_recordings_missing_embedding(self.db_path, "m", limit=10)
        self.assertEqual({row["id"] for row in missing}, {self.recording_a, self.recording_b})

        database.upsert_recording_embedding(self.db_path, self.recording_a, "m", [1.0])

        self.assertEqual(database.count_recordings_missing_embedding(self.db_path, "m"), 1)
        self.assertEqual(database.count_recording_embeddings(self.db_path, "m"), 1)
        missing = database.list_recordings_missing_embedding(self.db_path, "m", limit=10)
        self.assertEqual([row["id"] for row in missing], [self.recording_b])

    def test_a_recording_without_a_snapshot_never_counts_as_missing(self):
        database.update_recording_finished(self.db_path, self.recording_a, status="ready")
        self.assertEqual(database.count_recordings_missing_embedding(self.db_path, "m"), 0)
        self.assertEqual(database.list_recordings_missing_embedding(self.db_path, "m", limit=10), [])


if __name__ == "__main__":
    unittest.main()
