import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.tbc import automation, database


class AutomationRuleMatchingTests(unittest.TestCase):
    def setUp(self):
        self._tempfile = tempfile.NamedTemporaryFile(suffix=".sqlite3")
        self.db_path = self._tempfile.name
        database.initialize(self.db_path)

        self.camera_a = database.create_camera(
            self.db_path, name="Front door", host="192.0.2.10",
            onvif_port=8000, http_port=80, username="admin", password="secret",
        )
        self.camera_b = database.create_camera(
            self.db_path, name="Garage", host="192.0.2.11",
            onvif_port=8000, http_port=80, username="admin", password="secret",
        )
        self.face_id = database.create_known_face(self.db_path, name="Alex", embedding="[]")
        self.plate_id = database.create_known_plate(self.db_path, plate_text="B-TB 1234", label="Own car")
        self.channel_id = database.create_notification_channel(
            self.db_path, name="Test channel", kind="webhook", enabled=True, url="http://example.invalid/hook",
        )

    def tearDown(self):
        self._tempfile.close()

    def _create_rule(self, **overrides):
        values = {
            "name": "Rule",
            "enabled": True,
            "source": "recording_event",
            "camera_id": None,
            "event_type": None,
            "kind": None,
            "matched_face_id": None,
            "matched_plate_id": None,
            "unknown_only": False,
            "cooldown_seconds": 0,
            "notification_channel_id": self.channel_id,
            "title_template": "{{ title }}",
            "message_template": "{{ message }}",
        }
        values.update(overrides)
        return database.create_automation_rule(self.db_path, **values)

    def test_camera_scoped_rule_only_matches_its_camera(self):
        rule_id = self._create_rule(camera_id=self.camera_a)
        matches_a = database.list_matching_automation_rules(
            self.db_path, source="recording_event", camera_id=self.camera_a
        )
        matches_b = database.list_matching_automation_rules(
            self.db_path, source="recording_event", camera_id=self.camera_b
        )
        self.assertEqual([r["id"] for r in matches_a], [rule_id])
        self.assertEqual(matches_b, [])

    def test_unscoped_rule_matches_any_camera(self):
        rule_id = self._create_rule(camera_id=None)
        matches_a = database.list_matching_automation_rules(
            self.db_path, source="recording_event", camera_id=self.camera_a
        )
        matches_b = database.list_matching_automation_rules(
            self.db_path, source="recording_event", camera_id=self.camera_b
        )
        self.assertEqual([r["id"] for r in matches_a], [rule_id])
        self.assertEqual([r["id"] for r in matches_b], [rule_id])

    def test_event_type_scoping(self):
        rule_id = self._create_rule(event_type="recording_finished")
        matches = database.list_matching_automation_rules(
            self.db_path, source="recording_event", camera_id=self.camera_a, event_type="recording_finished"
        )
        no_matches = database.list_matching_automation_rules(
            self.db_path, source="recording_event", camera_id=self.camera_a, event_type="recording_failed"
        )
        self.assertEqual([r["id"] for r in matches], [rule_id])
        self.assertEqual(no_matches, [])

    def test_kind_scoping(self):
        rule_id = self._create_rule(source="recognition_event", kind="face")
        matches = database.list_matching_automation_rules(
            self.db_path, source="recognition_event", camera_id=self.camera_a, kind="face"
        )
        no_matches = database.list_matching_automation_rules(
            self.db_path, source="recognition_event", camera_id=self.camera_a, kind="plate"
        )
        self.assertEqual([r["id"] for r in matches], [rule_id])
        self.assertEqual(no_matches, [])

    def test_identity_specific_known_face(self):
        rule_id = self._create_rule(source="recognition_event", kind="face", matched_face_id=self.face_id)
        matches = database.list_matching_automation_rules(
            self.db_path, source="recognition_event", camera_id=self.camera_a, kind="face",
            matched_face_id=self.face_id,
        )
        no_matches_other_face = database.list_matching_automation_rules(
            self.db_path, source="recognition_event", camera_id=self.camera_a, kind="face",
            matched_face_id=self.face_id + 999,
        )
        no_matches_unknown = database.list_matching_automation_rules(
            self.db_path, source="recognition_event", camera_id=self.camera_a, kind="face",
        )
        self.assertEqual([r["id"] for r in matches], [rule_id])
        self.assertEqual(no_matches_other_face, [])
        self.assertEqual(no_matches_unknown, [])

    def test_identity_specific_known_plate(self):
        rule_id = self._create_rule(source="recognition_event", kind="plate", matched_plate_id=self.plate_id)
        matches = database.list_matching_automation_rules(
            self.db_path, source="recognition_event", camera_id=self.camera_a, kind="plate",
            matched_plate_id=self.plate_id,
        )
        self.assertEqual([r["id"] for r in matches], [rule_id])

    def test_identity_unknown_only(self):
        rule_id = self._create_rule(source="recognition_event", kind="face", unknown_only=True)
        matches_unknown = database.list_matching_automation_rules(
            self.db_path, source="recognition_event", camera_id=self.camera_a, kind="face",
        )
        no_matches_known = database.list_matching_automation_rules(
            self.db_path, source="recognition_event", camera_id=self.camera_a, kind="face",
            matched_face_id=self.face_id,
        )
        self.assertEqual([r["id"] for r in matches_unknown], [rule_id])
        self.assertEqual(no_matches_known, [])

    def test_identity_any_matches_known_and_unknown(self):
        rule_id = self._create_rule(source="recognition_event", kind="face")
        matches_known = database.list_matching_automation_rules(
            self.db_path, source="recognition_event", camera_id=self.camera_a, kind="face",
            matched_face_id=self.face_id,
        )
        matches_unknown = database.list_matching_automation_rules(
            self.db_path, source="recognition_event", camera_id=self.camera_a, kind="face",
        )
        self.assertEqual([r["id"] for r in matches_known], [rule_id])
        self.assertEqual([r["id"] for r in matches_unknown], [rule_id])

    def test_disabled_rule_never_matches(self):
        self._create_rule(enabled=False)
        matches = database.list_matching_automation_rules(
            self.db_path, source="recording_event", camera_id=self.camera_a
        )
        self.assertEqual(matches, [])

    def test_deleting_known_face_falls_rule_back_to_any(self):
        rule_id = self._create_rule(source="recognition_event", kind="face", matched_face_id=self.face_id)
        database.delete_known_face(self.db_path, self.face_id)
        rule = database.get_automation_rule(self.db_path, rule_id)
        self.assertIsNone(rule["matched_face_id"])
        matches = database.list_matching_automation_rules(
            self.db_path, source="recognition_event", camera_id=self.camera_a, kind="face",
        )
        self.assertEqual([r["id"] for r in matches], [rule_id])

    def test_deleting_notification_channel_cascades_rule_deletion(self):
        rule_id = self._create_rule()
        database.delete_notification_channel(self.db_path, self.channel_id)
        self.assertIsNone(database.get_automation_rule(self.db_path, rule_id))


class AutomationCooldownTests(unittest.TestCase):
    def setUp(self):
        self._tempfile = tempfile.NamedTemporaryFile(suffix=".sqlite3")
        self.db_path = self._tempfile.name
        database.initialize(self.db_path)
        self.channel_id = database.create_notification_channel(
            self.db_path, name="Test channel", kind="webhook", enabled=True, url="http://example.invalid/hook",
        )
        self.rule_id = database.create_automation_rule(
            self.db_path,
            name="Rule",
            enabled=True,
            source="recording_event",
            camera_id=None,
            event_type=None,
            kind=None,
            matched_face_id=None,
            matched_plate_id=None,
            unknown_only=False,
            cooldown_seconds=60,
            notification_channel_id=self.channel_id,
            title_template="{{ title }}",
            message_template="{{ message }}",
        )

    def tearDown(self):
        self._tempfile.close()

    def test_second_fire_within_cooldown_is_suppressed(self):
        self.assertTrue(database.try_fire_automation_rule(self.db_path, self.rule_id, cooldown_seconds=60))
        self.assertFalse(database.try_fire_automation_rule(self.db_path, self.rule_id, cooldown_seconds=60))

    def test_fire_allowed_again_after_cooldown_elapses(self):
        self.assertTrue(database.try_fire_automation_rule(self.db_path, self.rule_id, cooldown_seconds=60))
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE automation_rules SET last_fired_at = datetime('now', '-61 seconds') WHERE id = ?",
                (self.rule_id,),
            )
        self.assertTrue(database.try_fire_automation_rule(self.db_path, self.rule_id, cooldown_seconds=60))

    def test_no_cooldown_always_allows_firing(self):
        self.assertTrue(database.try_fire_automation_rule(self.db_path, self.rule_id, cooldown_seconds=0))
        self.assertTrue(database.try_fire_automation_rule(self.db_path, self.rule_id, cooldown_seconds=0))


class EvaluateAndFireTests(unittest.TestCase):
    def setUp(self):
        self._tempfile = tempfile.NamedTemporaryFile(suffix=".sqlite3")
        self.db_path = self._tempfile.name
        database.initialize(self.db_path)
        self.camera_id = database.create_camera(
            self.db_path, name="Front door", host="192.0.2.10",
            onvif_port=8000, http_port=80, username="admin", password="secret",
        )
        self.channel_id = database.create_notification_channel(
            self.db_path, name="Test channel", kind="webhook", enabled=True, url="http://example.invalid/hook",
        )
        database.create_automation_rule(
            self.db_path,
            name="Rule",
            enabled=True,
            source="recording_event",
            camera_id=None,
            event_type="recording_finished",
            kind=None,
            matched_face_id=None,
            matched_plate_id=None,
            unknown_only=False,
            cooldown_seconds=0,
            notification_channel_id=self.channel_id,
            title_template="{{ title }}",
            message_template="{{ message }}",
        )

    def tearDown(self):
        self._tempfile.close()

    def test_matching_rule_fires_the_channel(self):
        with patch("app.tbc.automation.notifications.send_via_channel") as send_mock:
            automation.evaluate_and_fire(
                self.db_path,
                source="recording_event",
                camera_id=self.camera_id,
                event_type="recording_finished",
                title="TBC: motion",
                message="Front door: clip saved",
            )
        send_mock.assert_called_once()
        _, args, kwargs = send_mock.mock_calls[0]
        self.assertEqual(args[1], "TBC: motion")
        self.assertEqual(args[2], "Front door: clip saved")

    def test_non_matching_event_type_does_not_fire(self):
        with patch("app.tbc.automation.notifications.send_via_channel") as send_mock:
            automation.evaluate_and_fire(
                self.db_path,
                source="recording_event",
                camera_id=self.camera_id,
                event_type="recording_failed",
                title="TBC: motion",
                message="Front door: failed",
            )
        send_mock.assert_not_called()

    def test_channel_send_failure_never_propagates(self):
        with patch("app.tbc.automation.notifications.send_via_channel", side_effect=RuntimeError("boom")):
            try:
                automation.evaluate_and_fire(
                    self.db_path,
                    source="recording_event",
                    camera_id=self.camera_id,
                    event_type="recording_finished",
                    title="TBC: motion",
                    message="Front door: clip saved",
                )
            except Exception as exc:  # pragma: no cover - test fails via re-raise below
                self.fail(f"evaluate_and_fire raised unexpectedly: {exc}")


if __name__ == "__main__":
    unittest.main()
