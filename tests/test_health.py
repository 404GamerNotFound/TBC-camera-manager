import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.tbc import database, health


class HealthTests(unittest.TestCase):
    def test_health_status_changes_create_events(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.upsert_health_status(
                handle.name,
                component_type="mqtt",
                component_id="broker",
                status="warning",
                message="MQTT deaktiviert",
            )
            database.upsert_health_status(
                handle.name,
                component_type="mqtt",
                component_id="broker",
                status="warning",
                message="MQTT weiterhin deaktiviert",
            )
            database.upsert_health_status(
                handle.name,
                component_type="mqtt",
                component_id="broker",
                status="ok",
                message="Broker erreichbar",
            )

            events = database.list_health_events(handle.name)

            self.assertEqual([event["status"] for event in events], ["ok", "warning"])
            self.assertEqual(events[0]["previous_status"], "warning")

    def test_stream_probe_warns_when_ffprobe_is_missing(self):
        with patch("app.tbc.health.shutil.which", return_value=None):
            status, message = health._probe_stream("rtsp://example/stream")

        self.assertEqual(status, "warning")
        self.assertIn("ffprobe", message)

    def test_stream_probe_accepts_video_stream(self):
        with patch("app.tbc.health.shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("app.tbc.health.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="video\n", stderr="")):
                status, message = health._probe_stream("rtsp://example/stream")

        self.assertEqual(status, "ok")
        self.assertEqual(message, "Stream lesbar")


if __name__ == "__main__":
    unittest.main()
