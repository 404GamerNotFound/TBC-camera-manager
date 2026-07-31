import json
import tempfile
import unittest

from app.tbc import database
from app.tbc.detection.audio_backend import AudioDetection
from app.tbc.detection.audio_supervisor import ActiveAudioTracker


def _audio_detection(key: str, confidence: float = 0.9) -> AudioDetection:
    return AudioDetection(label=key, detection_key=key, confidence=confidence)


class ActiveAudioTrackerTests(unittest.TestCase):
    def test_reports_all_canonical_keys_every_cycle(self):
        tracker = ActiveAudioTracker(active_timeout_seconds=3.0)
        rows = tracker.detection_rows(now=0.0)
        self.assertEqual({row["key"] for row in rows}, {"ai_bark", "ai_glass_break", "ai_smoke_alarm"})
        self.assertTrue(all(row["active"] is False for row in rows))
        self.assertTrue(all(row["source"] == "local_ai_audio" for row in rows))

    def test_heard_detection_becomes_active(self):
        tracker = ActiveAudioTracker(active_timeout_seconds=3.0)
        tracker.update([_audio_detection("ai_bark", 0.87)], now=10.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=10.0)}
        self.assertTrue(rows["ai_bark"]["active"])
        self.assertFalse(rows["ai_glass_break"]["active"])
        self.assertEqual(json.loads(rows["ai_bark"]["raw_value"])["confidence"], 0.87)

    def test_becomes_inactive_after_timeout_elapses(self):
        tracker = ActiveAudioTracker(active_timeout_seconds=3.0)
        tracker.update([_audio_detection("ai_smoke_alarm")], now=10.0)
        rows = {row["key"]: row for row in tracker.detection_rows(now=14.0)}
        self.assertFalse(rows["ai_smoke_alarm"]["active"])
        self.assertIsNone(rows["ai_smoke_alarm"]["raw_value"])


class ActiveAudioTrackerDatabaseIntegrationTests(unittest.TestCase):
    def test_rows_with_an_active_detection_are_storable(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Test",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            tracker = ActiveAudioTracker(active_timeout_seconds=3.0)
            tracker.update([_audio_detection("ai_glass_break", 0.95)])
            rows = tracker.detection_rows()

            database.replace_detections(handle.name, camera_id, rows)

            stored = {row["detection_key"]: row for row in database.list_detections(handle.name, camera_id)}
            self.assertTrue(bool(stored["ai_glass_break"]["active"]))
            self.assertEqual(json.loads(stored["ai_glass_break"]["raw_value"])["confidence"], 0.95)


class CameraAudioDetectionSettingsTests(unittest.TestCase):
    def test_defaults_to_none_when_unset(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Test",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            self.assertIsNone(database.get_camera_audio_detection_settings(handle.name, camera_id))

    def test_update_and_read_round_trip(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Test",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            database.update_camera_audio_detection_settings(
                handle.name, camera_id, enabled=True, confidence_threshold=0.75
            )
            settings = database.get_camera_audio_detection_settings(handle.name, camera_id)
            self.assertTrue(settings["enabled"])
            self.assertAlmostEqual(settings["confidence_threshold"], 0.75)

            enabled = database.list_enabled_camera_audio_detection_settings(handle.name)
            self.assertEqual(len(enabled), 1)
            self.assertEqual(enabled[0]["camera_id"], camera_id)


if __name__ == "__main__":
    unittest.main()
