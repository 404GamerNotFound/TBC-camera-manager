import unittest
from unittest.mock import patch

from app.tbc.camera_modules.onvif import OnvifProbe, OnvifStreamProfile
from app.tbc.camera_plugins.standard_onvif import service


class StandardOnvifServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_uses_discovered_stream_and_adds_credentials(self):
        camera = {
            "host": "192.0.2.30",
            "username": "camera user",
            "password": "p@ss",
            "onvif_port": 80,
        }
        onvif = OnvifProbe(
            success=True,
            message="ONVIF connection successful",
            manufacturer="Generic",
            model="IPC",
            stream_uris=["rtsp://192.0.2.30:554/main"],
            event_detection_keys={"motion"},
        )

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(snapshot.stream_uri, "rtsp://camera%20user:p%40ss@192.0.2.30:554/main")
        motion = next(row for row in snapshot.detections if row["key"] == "motion")
        self.assertTrue(motion["supported"])

    async def test_probe_requires_successful_onvif_connection(self):
        onvif = OnvifProbe(False, "ONVIF connection failed")
        camera = {"host": "192.0.2.30", "username": "camera", "password": "secret", "onvif_port": 80}

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.status, "error")
        self.assertIsNone(snapshot.stream_uri)

    async def test_single_lens_camera_has_no_channels(self):
        camera = {"host": "192.0.2.30", "username": "camera", "password": "secret", "onvif_port": 80}
        onvif = OnvifProbe(
            success=True,
            message="ONVIF connection successful",
            stream_uris=["rtsp://192.0.2.30:554/main"],
            stream_profiles=[OnvifStreamProfile(uri="rtsp://192.0.2.30:554/main")],
        )

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(snapshot.channels, [])

    async def test_multi_lens_camera_gets_one_channel_per_lens(self):
        camera = {"host": "192.0.2.30", "username": "camera", "password": "secret", "onvif_port": 80}
        onvif = OnvifProbe(
            success=True,
            message="ONVIF connection successful",
            stream_uris=["rtsp://192.0.2.30:554/lens1", "rtsp://192.0.2.30:554/lens2"],
            stream_profiles=[
                OnvifStreamProfile(uri="rtsp://192.0.2.30:554/lens1", source_token="lens-1"),
                OnvifStreamProfile(uri="rtsp://192.0.2.30:554/lens2", source_token="lens-2"),
            ],
        )

        with patch.object(service, "probe_onvif", return_value=onvif):
            snapshot = await service.probe_camera(camera)

        self.assertEqual(len(snapshot.channels), 2)
        self.assertEqual(snapshot.channels[0]["channel_index"], 0)
        self.assertEqual(snapshot.channels[0]["name"], "Lens 1")
        self.assertEqual(snapshot.channels[0]["stream_uri"], "rtsp://camera:secret@192.0.2.30:554/lens1")
        self.assertEqual(snapshot.channels[1]["channel_index"], 1)
        self.assertEqual(snapshot.channels[1]["name"], "Lens 2")
        # The plain stream_uri (used where only a single stream is shown)
        # still points at the first lens for backward compatibility.
        self.assertEqual(snapshot.stream_uri, "rtsp://camera:secret@192.0.2.30:554/lens1")


if __name__ == "__main__":
    unittest.main()
