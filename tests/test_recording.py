import tempfile
import unittest
from pathlib import Path

from app.tbc import database, recording
from app.tbc.maintenance import apply_cleanup, cleanup_preview
from app.tbc.recording import ContinuousRecordingManager, _bbox_for_active_event, _drawbox_filter, _motion_is_active


class RecordingTests(unittest.TestCase):
    def test_default_storage_target_uses_configured_path(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name, "/recordings/nas")
            targets = database.list_storage_targets(handle.name)

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["kind"], "local")
        self.assertEqual(targets[0]["local_path"], "/recordings/nas")

    def test_motion_detection_accepts_single_and_channel_keys(self):
        self.assertTrue(_motion_is_active([{"key": "motion", "active": True}]))
        self.assertTrue(_motion_is_active([{"key": "ch1:motion", "active": True}]))
        self.assertFalse(_motion_is_active([{"key": "person", "active": True}]))
        self.assertFalse(_motion_is_active([{"key": "motion", "active": False}]))

    def test_retention_cleanup_preview_and_apply_by_age(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Einfahrt",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            recording_id = database.create_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=1,
                detection_key="person",
                event_label="Person",
                storage_kind="local",
                started_at="2000-06-01T12:00:00",
            )
            database.update_recording_finished(
                handle.name,
                recording_id,
                status="ready",
                size_bytes=1024,
                ended_at="2000-06-01T12:00:30",
            )
            database.create_retention_rule(
                handle.name,
                name="Personen 7 Tage",
                enabled=True,
                camera_id=camera_id,
                detection_key="person",
                max_age_days=7,
                max_size_gb=None,
            )

            preview = cleanup_preview(handle.name)
            deleted = apply_cleanup(handle.name)

            self.assertEqual([item["id"] for item in preview], [recording_id])
            self.assertEqual(deleted, 1)
            self.assertIsNone(database.get_recording(handle.name, recording_id))

    def test_locked_recording_is_exempt_from_retention_cleanup(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Einfahrt",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            recording_id = database.create_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=1,
                detection_key="person",
                event_label="Person",
                storage_kind="local",
                started_at="2000-06-01T12:00:00",
            )
            database.update_recording_finished(
                handle.name,
                recording_id,
                status="ready",
                size_bytes=1024,
                ended_at="2000-06-01T12:00:30",
            )
            database.create_retention_rule(
                handle.name,
                name="Personen 7 Tage",
                enabled=True,
                camera_id=camera_id,
                detection_key="person",
                max_age_days=7,
                max_size_gb=None,
            )
            database.set_recording_locked(handle.name, recording_id, True)

            preview = cleanup_preview(handle.name)
            deleted = apply_cleanup(handle.name)

            self.assertEqual(preview, [])
            self.assertEqual(deleted, 0)
            self.assertIsNotNone(database.get_recording(handle.name, recording_id))

    def test_set_recording_locked_toggles_flag_and_timestamp(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Einfahrt",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            recording_id = database.create_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=1,
                detection_key="person",
                event_label="Person",
                storage_kind="local",
                started_at="2000-06-01T12:00:00",
            )

            database.set_recording_locked(handle.name, recording_id, True)
            locked = database.get_recording(handle.name, recording_id)
            self.assertTrue(locked["locked"])
            self.assertIsNotNone(locked["locked_at"])

            database.set_recording_locked(handle.name, recording_id, False)
            unlocked = database.get_recording(handle.name, recording_id)
            self.assertFalse(unlocked["locked"])
            self.assertIsNone(unlocked["locked_at"])

    def test_retention_size_limit_keeps_newest_matching_clip(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Garage",
                host="192.0.2.20",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            older_id = database.create_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=1,
                detection_key="vehicle",
                event_label="Fahrzeug",
                storage_kind="local",
                started_at="2026-07-01T10:00:00",
            )
            newer_id = database.create_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=1,
                detection_key="vehicle",
                event_label="Fahrzeug",
                storage_kind="local",
                started_at="2026-07-02T10:00:00",
            )
            database.update_recording_finished(handle.name, older_id, status="ready", size_bytes=700)
            database.update_recording_finished(handle.name, newer_id, status="ready", size_bytes=700)
            database.create_retention_rule(
                handle.name,
                name="Fahrzeuge klein halten",
                enabled=True,
                camera_id=camera_id,
                detection_key="vehicle",
                max_age_days=None,
                max_size_gb=0.000001,
            )

            preview = cleanup_preview(handle.name)

            self.assertEqual([item["id"] for item in preview], [older_id])
            self.assertIsNotNone(database.get_recording(handle.name, newer_id))

    def test_storage_target_retention_is_included_in_cleanup_preview(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.update_storage_target(
                handle.name,
                1,
                name="Lokaler Container-Speicher",
                kind="local",
                local_path="/recordings",
                retention_days=7,
                retention_max_gb=None,
            )
            camera_id = database.create_camera(
                handle.name,
                name="Hof",
                host="192.0.2.40",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            recording_id = database.create_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=1,
                detection_key="motion",
                event_label="Bewegung",
                storage_kind="local",
                started_at="2000-01-01T12:00:00",
            )
            database.update_recording_finished(handle.name, recording_id, status="ready", size_bytes=256)

            preview = cleanup_preview(handle.name)

            self.assertEqual([item["id"] for item in preview], [recording_id])


class ContinuousRecordingTests(unittest.TestCase):
    def test_continuous_settings_roundtrip_and_range_query(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Terrasse",
                host="192.0.2.30",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            database.update_camera_continuous_settings(
                handle.name,
                camera_id,
                continuous_recording_enabled=True,
                continuous_segment_seconds=120,
                continuous_storage_id=1,
            )
            camera = database.get_camera(handle.name, camera_id)
            self.assertEqual(camera["continuous_recording_enabled"], 1)
            self.assertEqual(camera["continuous_segment_seconds"], 120)

            storage = database.list_storage_targets(handle.name)[0]
            database.create_continuous_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=storage["id"],
                storage_kind="local",
                file_name="seg1.mp4",
                local_path="/tmp/seg1.mp4",
                remote_key=None,
                duration_seconds=120,
                size_bytes=1000,
                started_at="2026-07-11T01:00:00",
                ended_at="2026-07-11T01:02:00",
            )
            database.create_continuous_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=storage["id"],
                storage_kind="local",
                file_name="seg2.mp4",
                local_path="/tmp/seg2.mp4",
                remote_key=None,
                duration_seconds=120,
                size_bytes=1000,
                started_at="2026-07-12T01:00:00",
                ended_at="2026-07-12T01:02:00",
            )

            rows = database.list_recordings_for_range(
                handle.name,
                camera_id=camera_id,
                start_at="2026-07-11T00:00:00",
                end_at="2026-07-12T00:00:00",
            )
            self.assertEqual([row["file_name"] for row in rows], ["seg1.mp4"])
            self.assertEqual(
                database.list_continuous_file_names(handle.name, camera_id),
                ["seg2.mp4", "seg1.mp4"],
            )

    def test_list_recordings_excludes_continuous_by_default(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Garten",
                host="192.0.2.31",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            storage = database.list_storage_targets(handle.name)[0]
            database.create_continuous_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=storage["id"],
                storage_kind="local",
                file_name="seg1.mp4",
                local_path="/tmp/seg1.mp4",
                remote_key=None,
                duration_seconds=300,
                size_bytes=1000,
                started_at="2026-07-11T01:00:00",
                ended_at="2026-07-11T01:05:00",
            )
            event_id = database.create_recording(
                handle.name,
                camera_id=camera_id,
                storage_id=storage["id"],
                detection_key="motion",
                event_label="Bewegung",
                storage_kind="local",
                started_at="2026-07-11T02:00:00",
            )
            database.update_recording_finished(handle.name, event_id, status="ready", size_bytes=500)

            default_rows = database.list_recordings(handle.name, camera_id=camera_id)
            self.assertEqual([row["detection_key"] for row in default_rows], ["motion"])

            continuous_rows = database.list_recordings(handle.name, camera_id=camera_id, detection_key="continuous")
            self.assertEqual(len(continuous_rows), 1)

    def test_collect_segments_registers_completed_files_and_skips_open_one(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle, tempfile.TemporaryDirectory() as storage_dir, tempfile.TemporaryDirectory() as scratch_dir:
            database.initialize(handle.name, storage_dir)
            camera_id = database.create_camera(
                handle.name,
                name="Zufahrt",
                host="192.0.2.32",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            camera = database.get_camera(handle.name, camera_id)
            camera["continuous_segment_seconds"] = 60

            original_root = recording.CONTINUOUS_ROOT
            recording.CONTINUOUS_ROOT = Path(scratch_dir)
            try:
                work_dir = Path(scratch_dir) / str(camera_id)
                work_dir.mkdir(parents=True)
                first = work_dir / "zufahrt_20260711T010000.mp4"
                second = work_dir / "zufahrt_20260711T010100.mp4"
                first.write_bytes(b"fake-mp4-data")
                second.write_bytes(b"fake-mp4-data")

                manager = ContinuousRecordingManager(handle.name)
                manager._collect_segments(camera)

                rows = database.list_recordings_for_range(
                    handle.name,
                    camera_id=camera_id,
                    start_at="2026-07-11T00:00:00",
                    end_at="2026-07-12T00:00:00",
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["file_name"], first.name)
                self.assertEqual(rows[0]["detection_key"], "continuous")
                self.assertFalse(first.exists())
                self.assertTrue(second.exists())
            finally:
                recording.CONTINUOUS_ROOT = original_root


class BboxForActiveEventTests(unittest.TestCase):
    def test_extracts_box_for_matching_active_local_ai_detection(self):
        detections = [
            {
                "key": "ai_person",
                "active": True,
                "source": "local_ai",
                "raw_value": '{"confidence": 0.9, "box": [0.1, 0.2, 0.5, 0.6]}',
            }
        ]
        self.assertEqual(_bbox_for_active_event(detections, "ai_person"), (0.1, 0.2, 0.5, 0.6))

    def test_ignores_camera_native_detections_without_local_ai_source(self):
        detections = [{"key": "person", "active": True, "source": "onvif", "raw_value": None}]
        self.assertIsNone(_bbox_for_active_event(detections, "person"))

    def test_ignores_inactive_detections(self):
        detections = [
            {
                "key": "ai_person",
                "active": False,
                "source": "local_ai",
                "raw_value": '{"confidence": 0.9, "box": [0.1, 0.2, 0.5, 0.6]}',
            }
        ]
        self.assertIsNone(_bbox_for_active_event(detections, "ai_person"))

    def test_handles_missing_or_malformed_raw_value(self):
        detections = [{"key": "ai_person", "active": True, "source": "local_ai", "raw_value": None}]
        self.assertIsNone(_bbox_for_active_event(detections, "ai_person"))
        detections = [{"key": "ai_person", "active": True, "source": "local_ai", "raw_value": "not json"}]
        self.assertIsNone(_bbox_for_active_event(detections, "ai_person"))

    def test_matches_channel_prefixed_keys(self):
        detections = [
            {
                "key": "ch1:ai_person",
                "active": True,
                "source": "local_ai",
                "raw_value": '{"confidence": 0.8, "box": [0.0, 0.0, 1.0, 1.0]}',
            }
        ]
        self.assertEqual(_bbox_for_active_event(detections, "ai_person"), (0.0, 0.0, 1.0, 1.0))


class DrawboxFilterTests(unittest.TestCase):
    def test_returns_none_without_a_box(self):
        self.assertIsNone(_drawbox_filter(None))

    def test_builds_expected_expression(self):
        expression = _drawbox_filter((0.1, 0.2, 0.5, 0.6))
        self.assertIn("x=iw*0.1000", expression)
        self.assertIn("y=ih*0.2000", expression)
        self.assertIn("w=iw*0.4000", expression)
        self.assertIn("h=ih*0.4000", expression)
        self.assertIn("color=red", expression)

    def test_clamps_out_of_range_values(self):
        expression = _drawbox_filter((-0.5, -0.5, 1.5, 1.5))
        self.assertIn("x=iw*0.0000", expression)
        self.assertIn("y=ih*0.0000", expression)
        self.assertIn("w=iw*1.0000", expression)
        self.assertIn("h=ih*1.0000", expression)


if __name__ == "__main__":
    unittest.main()
