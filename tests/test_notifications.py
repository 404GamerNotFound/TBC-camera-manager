import tempfile
import unittest
from unittest.mock import patch

from app.tbc import database, notifications


class NotificationTemplateTests(unittest.TestCase):
    def test_event_templates_control_delivery_and_render_text(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            templates = database.notification_event_defaults()
            for template in templates:
                template["enabled"] = template["event_type"] == "recording_finished"
            finished = next(template for template in templates if template["event_type"] == "recording_finished")
            finished["title_template"] = "Alert: {{ title }}"
            finished["message_template"] = "{{ event_type }} — {{ message }}"
            database.create_notification_channel(
                handle.name,
                name="Webhook",
                kind="webhook",
                enabled=True,
                include_snapshot=False,
                event_filter="recording_finished",
                url="https://example.invalid/hook",
                event_templates=templates,
            )

            with patch("app.tbc.notifications._send") as send:
                notifications.notify_event(
                    handle.name,
                    event_type="recording_finished",
                    title="Clip saved",
                    message="Driveway",
                )
                notifications.notify_event(
                    handle.name,
                    event_type="recording_failed",
                    title="Clip failed",
                    message="Driveway",
                )

            send.assert_called_once()
            _, title, message, _, _ = send.call_args.args
            self.assertEqual(title, "Alert: Clip saved")
            self.assertEqual(message, "recording_finished — Driveway")

    def test_legacy_event_filter_remains_effective_without_saved_templates(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            channel_id = database.create_notification_channel(
                handle.name,
                name="Legacy webhook",
                kind="webhook",
                enabled=True,
                include_snapshot=False,
                event_filter="recording_failed",
                url="https://example.invalid/hook",
            )
            events = database.list_notification_event_templates(handle.name, channel_id, "recording_failed")

            self.assertTrue(next(event for event in events if event["event_type"] == "recording_failed")["enabled"])
            self.assertFalse(next(event for event in events if event["event_type"] == "recording_finished")["enabled"])


if __name__ == "__main__":
    unittest.main()
