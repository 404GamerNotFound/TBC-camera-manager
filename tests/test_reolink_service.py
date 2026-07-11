import asyncio
import sys
import types
import unittest
from unittest.mock import patch

from app.tbc.reolink import service


class FakeReolinkHost:
    def __init__(self):
        self.calls = []

    async def get_rtsp_stream_source(self, channel, stream, check):
        self.calls.append((channel, stream, check))
        if stream == "sub":
            return "rtsp://example/sub"
        return "rtsp://example/main"


class FakePerformanceHost:
    async def send(self, body):
        return [
            {
                "cmd": "GetPerformance",
                "code": 0,
                "value": {"Performance": {"cpuUsed": 27, "codecRate": 6794, "netThroughput": 42}},
            }
        ]


class FakeBaichuan:
    def __init__(self):
        self.callback = None
        self.subscribed = asyncio.Event()
        self.unsubscribed = False

    def register_callback(self, key, callback):
        self.callback = callback

    def unregister_callback(self, key):
        self.callback = None

    async def subscribe_events(self):
        self.subscribed.set()

    async def unsubscribe_events(self):
        self.unsubscribed = True


class FakeEventHost:
    instance = None

    def __init__(self, *args, **kwargs):
        type(self).instance = self
        self.channels = [0]
        self.baichuan = FakeBaichuan()
        self.motion = False
        self.closed = False

    async def get_host_data(self):
        return None

    async def get_states(self):
        return None

    def supported(self, channel, feature):
        return feature == "motion_detection"

    def motion_detected(self, channel):
        return self.motion

    async def logout(self):
        self.closed = True


class ReolinkServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_rtsp_stream_uri_uses_reolink_aio_stream_source(self):
        host = FakeReolinkHost()

        uri = await service._rtsp_stream_uri(host, 0)

        self.assertEqual(uri, "rtsp://example/sub")
        self.assertEqual(host.calls[0], (0, "sub", False))

    async def test_host_hint_flags_common_192_169_typo(self):
        self.assertIn("192.168", service._host_hint("192.169.1.236"))
        self.assertIsNone(service._host_hint("192.168.1.236"))

    async def test_performance_metrics_are_normalized(self):
        metrics = await service._performance_metrics(FakePerformanceHost())

        self.assertEqual(
            metrics,
            {"cpu_used": 27, "codec_rate": 6794, "net_throughput": 42},
        )

    async def test_performance_metrics_are_optional(self):
        class UnsupportedHost:
            async def send(self, body):
                return [{"cmd": "GetPerformance", "code": 1}]

        self.assertEqual(await service._performance_metrics(UnsupportedHost()), {})

    async def test_event_monitor_forwards_tcp_push_state_and_cleans_up(self):
        api_module = types.ModuleType("reolink_aio.api")
        api_module.Host = FakeEventHost
        package = types.ModuleType("reolink_aio")
        received = []
        received_event = asyncio.Event()

        async def callback(detections):
            received.append(detections)
            if any(row["key"] == "motion" and row["active"] for row in detections):
                received_event.set()

        camera = {"id": 1, "host": "camera", "username": "u", "password": "p", "http_port": 80}
        with patch.dict(sys.modules, {"reolink_aio": package, "reolink_aio.api": api_module}):
            task = asyncio.create_task(service.monitor_events(camera, callback))
            await asyncio.sleep(0)
            await asyncio.wait_for(FakeEventHost.instance.baichuan.subscribed.wait(), 1)
            FakeEventHost.instance.motion = True
            FakeEventHost.instance.baichuan.callback()
            await asyncio.wait_for(received_event.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertTrue(any(row["active"] for row in received[-1] if row["key"] == "motion"))
        self.assertTrue(FakeEventHost.instance.baichuan.unsubscribed)
        self.assertTrue(FakeEventHost.instance.closed)


if __name__ == "__main__":
    unittest.main()
