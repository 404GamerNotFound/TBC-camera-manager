import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.tbc.snapshots import DashboardSnapshotManager


class DashboardSnapshotTests(unittest.TestCase):
    def test_snapshot_is_created_atomically_and_reused_until_due(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            Path(command[-1]).write_bytes(b"\xff\xd8snapshot\xff\xd9")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as root, patch("app.tbc.snapshots.shutil.which", return_value="/usr/bin/ffmpeg"), patch(
            "app.tbc.snapshots.subprocess.run", side_effect=fake_run
        ):
            manager = DashboardSnapshotManager(root, interval_seconds=600)
            first = manager.refresh_if_due(7, "rtsp://user:secret@camera/live")
            second = manager.refresh_if_due(7, "rtsp://user:secret@camera/live")

        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("secret", str(first))

    def test_stale_snapshot_is_replaced(self):
        def fake_run(command, **kwargs):
            Path(command[-1]).write_bytes(b"new image")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as root, patch("app.tbc.snapshots.shutil.which", return_value="ffmpeg"), patch(
            "app.tbc.snapshots.subprocess.run", side_effect=fake_run
        ) as run:
            manager = DashboardSnapshotManager(root, interval_seconds=60)
            destination = manager.path_for(3)
            destination.write_bytes(b"old image")
            os.utime(destination, (1, 1))
            result = manager.refresh_if_due(3, "rtsp://camera/live")
            content = result.read_bytes() if result else b""

        self.assertEqual(content, b"new image")
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
