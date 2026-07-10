import unittest

from app.tbc.reolink import service


class FakeReolinkHost:
    def __init__(self):
        self.calls = []

    async def get_rtsp_stream_source(self, channel, stream, check):
        self.calls.append((channel, stream, check))
        if stream == "sub":
            return "rtsp://example/sub"
        return "rtsp://example/main"


class ReolinkServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_rtsp_stream_uri_uses_reolink_aio_stream_source(self):
        host = FakeReolinkHost()

        uri = await service._rtsp_stream_uri(host, 0)

        self.assertEqual(uri, "rtsp://example/sub")
        self.assertEqual(host.calls[0], (0, "sub", False))

    async def test_host_hint_flags_common_192_169_typo(self):
        self.assertIn("192.168", service._host_hint("192.169.1.236"))
        self.assertIsNone(service._host_hint("192.168.1.236"))


if __name__ == "__main__":
    unittest.main()
