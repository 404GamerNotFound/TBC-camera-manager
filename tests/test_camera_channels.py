import tempfile
import unittest

from app.tbc import database
from app.tbc.channels import apply_channel_enabled_filter


class CameraChannelTests(unittest.TestCase):
    def test_channel_upsert_and_admin_update(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="NVR",
                host="192.0.2.30",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )
            database.upsert_camera_channels(
                handle.name,
                camera_id,
                [
                    {"channel_index": 0, "name": "Kanal 1", "stream_uri": "rtsp://example/0"},
                    {"channel_index": 1, "name": "Kanal 2", "stream_uri": "rtsp://example/1"},
                ],
            )
            first = database.list_camera_channels(handle.name, camera_id)[0]
            database.update_camera_channel(handle.name, int(first["id"]), name="Einfahrt", enabled=False)
            database.upsert_camera_channels(
                handle.name,
                camera_id,
                [{"channel_index": 0, "name": "Auto Name", "stream_uri": "rtsp://example/new"}],
            )

            channels = database.list_camera_channels(handle.name, camera_id)

            self.assertEqual(len(channels), 2)
            self.assertEqual(channels[0]["name"], "Einfahrt")
            self.assertEqual(channels[0]["enabled"], 0)
            self.assertEqual(channels[0]["stream_uri"], "rtsp://example/new")

    def test_disabled_channel_filter_suppresses_active_detections(self):
        detections = [
            {"key": "ch0:person", "channel": 0, "active": True},
            {"key": "ch1:person", "channel": 1, "active": True},
            {"key": "motion", "channel": None, "active": True},
        ]
        channels = [
            {"channel_index": 0, "enabled": 0},
            {"channel_index": 1, "enabled": 1},
        ]

        filtered = apply_channel_enabled_filter(detections, channels)

        self.assertFalse(filtered[0]["active"])
        self.assertTrue(filtered[1]["active"])
        self.assertTrue(filtered[2]["active"])


if __name__ == "__main__":
    unittest.main()
