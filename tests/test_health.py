import tempfile
import unittest
from pathlib import Path
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

    def test_cpu_percent_from_proc_totals(self):
        percent = health._cpu_percent_from_totals((100, 40), (200, 60))

        self.assertEqual(percent, 80.0)

    def test_proc_memory_usage_formats_current_ram(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".meminfo") as handle:
            handle.write("MemTotal:       1048576 kB\n")
            handle.write("MemAvailable:    262144 kB\n")
            handle.flush()

            usage = health._read_proc_memory(Path(handle.name))

        self.assertIsNotNone(usage)
        self.assertEqual(usage["percent"], 75.0)
        self.assertEqual(usage["used_mb"], 768)
        self.assertEqual(usage["total_mb"], 1024)


if __name__ == "__main__":
    unittest.main()
