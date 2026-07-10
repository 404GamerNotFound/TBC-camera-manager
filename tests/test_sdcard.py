import sys
import unittest
from datetime import datetime, timedelta
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import patch

from app.tbc.reolink import sdcard


class FakeStream:
    def __init__(self):
        self._chunks = [b"one", b"two", b""]

    async def read(self, _chunk_size):
        return self._chunks.pop(0)


class FakeHost:
    is_nvr = False
    stream_channels = [0]

    def __init__(self):
        self.logged_out = False

    async def get_host_data(self):
        return None

    async def download_vod(self, **_kwargs):
        return SimpleNamespace(
            filename="clip.mp4",
            length=6,
            stream=FakeStream(),
            close=lambda: None,
        )

    async def logout(self):
        self.logged_out = True


class FakeVodFile:
    file_name = "Mp4Record/2026-07-10/RecM01_20260710_100000_100030_ABCD_001000.mp4"
    start_time = datetime(2026, 7, 10, 10, 0, 0)
    end_time = datetime(2026, 7, 10, 10, 0, 30)
    start_time_id = "20260710100000"
    end_time_id = "20260710100030"
    duration = timedelta(seconds=30)
    size = 1024
    triggers = 0


class SdCardTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_stream_closes_reolink_session_after_read(self):
        host = FakeHost()
        camera = {"host": "192.0.2.10", "username": "admin", "password": "secret", "http_port": 80}

        with patch("app.tbc.reolink.sdcard._host", return_value=host):
            download = await sdcard.open_sd_card_download(
                camera,
                channel=0,
                source="clip.mp4",
                start_id="20260710100000",
                end_id="20260710100030",
            )
            chunks = [chunk async for chunk in download.chunks()]

        self.assertEqual(chunks, [b"one", b"two"])
        self.assertTrue(host.logged_out)

    def test_vod_file_row_formats_reolink_file(self):
        row = sdcard._vod_file_row(FakeVodFile(), channel=0, stream="main")

        self.assertEqual(row["file_name"], "RecM01_20260710_100000_100030_ABCD_001000.mp4")
        self.assertEqual(row["start_id"], "20260710100000")
        self.assertEqual(row["duration_seconds"], 30)

    def test_host_uses_configured_http_port_without_https_autodetect(self):
        created = {}

        class FakeReolinkHost:
            def __init__(self, host, username, password, *, port, use_https, timeout):
                created.update(
                    {
                        "host": host,
                        "username": username,
                        "password": password,
                        "port": port,
                        "use_https": use_https,
                        "timeout": timeout,
                    }
                )

        package = ModuleType("reolink_aio")
        api = ModuleType("reolink_aio.api")
        api.Host = FakeReolinkHost
        with patch.dict(sys.modules, {"reolink_aio": package, "reolink_aio.api": api}):
            sdcard._host({"host": "192.0.2.10", "username": "admin", "password": "secret", "http_port": 80})

        self.assertEqual(created["port"], 80)
        self.assertFalse(created["use_https"])


if __name__ == "__main__":
    unittest.main()
