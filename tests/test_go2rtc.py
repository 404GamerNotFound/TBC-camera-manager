import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from app.tbc.go2rtc import Go2rtcManager


class Go2rtcManagerStartStopTests(unittest.TestCase):
    def test_start_raises_when_binary_missing(self):
        with TemporaryDirectory() as temp_dir:
            manager = Go2rtcManager(temp_dir, binary_path="tbc-go2rtc-does-not-exist")

            with self.assertRaises(RuntimeError):
                manager.start()

    def test_start_writes_loopback_only_config_and_launches_process(self):
        with TemporaryDirectory() as temp_dir:
            manager = Go2rtcManager(temp_dir, binary_path="go2rtc")
            process = MagicMock()
            process.poll.return_value = None
            process.stderr = iter([])
            process.wait.return_value = 0

            with patch("shutil.which", return_value="/usr/local/bin/go2rtc"):
                with patch("subprocess.Popen", return_value=process) as popen:
                    manager.start()

            config_path = Path(temp_dir) / "go2rtc.yaml"
            config_text = config_path.read_text(encoding="utf-8")
            self.assertIn('listen: "127.0.0.1:1984"', config_text)
            self.assertIn('listen: ":8555"', config_text)

            args, kwargs = popen.call_args
            self.assertEqual(args[0], ["go2rtc", "-config", str(config_path)])
            self.assertEqual(kwargs["stderr"], -1)

    def test_start_is_idempotent_while_already_running(self):
        with TemporaryDirectory() as temp_dir:
            manager = Go2rtcManager(temp_dir, binary_path="go2rtc")
            process = MagicMock()
            process.poll.return_value = None
            process.stderr = iter([])
            process.wait.return_value = 0

            with patch("shutil.which", return_value="/usr/local/bin/go2rtc"):
                with patch("subprocess.Popen", return_value=process) as popen:
                    manager.start()
                    manager.start()

            self.assertEqual(popen.call_count, 1)

    def test_status_reflects_process_lifecycle(self):
        with TemporaryDirectory() as temp_dir:
            manager = Go2rtcManager(temp_dir, binary_path="go2rtc")
            self.assertEqual(manager.status(), "stopped")

            process = MagicMock()
            process.poll.return_value = None
            process.stderr = iter([])
            process.wait.return_value = 0
            with patch("shutil.which", return_value="/usr/local/bin/go2rtc"):
                with patch("subprocess.Popen", return_value=process):
                    manager.start()
            self.assertEqual(manager.status(), "running")

            process.poll.return_value = 1
            self.assertEqual(manager.status(), "failed")

    def test_stop_terminates_running_process(self):
        with TemporaryDirectory() as temp_dir:
            manager = Go2rtcManager(temp_dir, binary_path="go2rtc")
            process = MagicMock()
            process.poll.return_value = None
            process.stderr = iter([])
            process.wait.return_value = 0
            with patch("shutil.which", return_value="/usr/local/bin/go2rtc"):
                with patch("subprocess.Popen", return_value=process):
                    manager.start()

            manager.stop()

            process.terminate.assert_called_once()
            process.wait.assert_any_call(timeout=5)
            self.assertEqual(manager.status(), "stopped")

    def test_stop_without_start_is_a_no_op(self):
        with TemporaryDirectory() as temp_dir:
            manager = Go2rtcManager(temp_dir, binary_path="go2rtc")
            manager.stop()
            self.assertEqual(manager.status(), "stopped")


class Go2rtcManagerApiTests(unittest.TestCase):
    def _mock_response(self, body: bytes = b"") -> MagicMock:
        response = MagicMock()
        response.read.return_value = body
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def test_register_stream_calls_put_with_name_and_src(self):
        manager = Go2rtcManager("/tmp/tbc-go2rtc-unused")
        with patch("urllib.request.urlopen", return_value=self._mock_response()) as urlopen:
            manager.register_stream("cam-1", "rtsp://user:pw@camera.local/stream")

        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertIn("/api/streams?", request.full_url)
        self.assertIn("name=cam-1", request.full_url)
        self.assertIn("rtsp%3A%2F%2Fuser%3Apw%40camera.local%2Fstream", request.full_url)

    def test_unregister_stream_calls_delete_with_src(self):
        manager = Go2rtcManager("/tmp/tbc-go2rtc-unused")
        with patch("urllib.request.urlopen", return_value=self._mock_response()) as urlopen:
            manager.unregister_stream("cam-1")

        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_method(), "DELETE")
        self.assertIn("src=cam-1", request.full_url)

    def test_exchange_sdp_posts_offer_and_returns_answer(self):
        manager = Go2rtcManager("/tmp/tbc-go2rtc-unused")
        with patch("urllib.request.urlopen", return_value=self._mock_response(b"v=0\r\nanswer-sdp")) as urlopen:
            answer = manager.exchange_sdp("cam-1", "v=0\r\noffer-sdp")

        self.assertEqual(answer, "v=0\r\nanswer-sdp")
        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_method(), "POST")
        self.assertIn("/api/webrtc?src=cam-1", request.full_url)
        self.assertEqual(request.get_header("Content-type"), "application/sdp")
        self.assertEqual(request.data, b"v=0\r\noffer-sdp")

    def test_exchange_sdp_wraps_network_errors(self):
        manager = Go2rtcManager("/tmp/tbc-go2rtc-unused")
        error = urllib.error.URLError("connection refused")
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError):
                manager.exchange_sdp("cam-1", "v=0\r\noffer-sdp")

    def test_api_call_wraps_network_errors(self):
        manager = Go2rtcManager("/tmp/tbc-go2rtc-unused")
        error = urllib.error.URLError("connection refused")
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError):
                manager.register_stream("cam-1", "rtsp://camera.local/stream")


if __name__ == "__main__":
    unittest.main()
