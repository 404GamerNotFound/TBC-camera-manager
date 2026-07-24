import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest.mock import patch

from app.tbc.live import (
    LiveManager,
    _is_nonfatal_hls_warning,
    _live_ffmpeg_command,
    diagnose_stream_open_failure,
    redact_rtsp_credentials,
)


class LiveTests(unittest.TestCase):
    def test_redact_rtsp_credentials_masks_username_and_password(self):
        uri = "rtsp://user:pw@192.168.1.236:554/Preview_01_sub"

        self.assertEqual(
            redact_rtsp_credentials(uri),
            "rtsp://***:***@192.168.1.236:554/Preview_01_sub",
        )

    def test_redact_rtsp_credentials_masks_urls_inside_messages(self):
        message = "Error at rtsp://user:pw@camera.local/stream: connection failed"

        self.assertNotIn("user:pw", redact_rtsp_credentials(message))

    def test_redact_rtsps_credentials_masks_username_and_password(self):
        self.assertEqual(
            redact_rtsp_credentials("rtsps://secure:secret@nvr.local:7441/camera"),
            "rtsps://***:***@nvr.local:7441/camera",
        )

    def test_live_ffmpeg_command_generates_timestamps(self):
        command = _live_ffmpeg_command(
            "rtsp://example/stream",
            Path("/tmp/live/segment%03d.ts"),
            Path("/tmp/live/index.m3u8"),
        )

        self.assertIn("+genpts+discardcorrupt", command)
        self.assertIn("-use_wallclock_as_timestamps", command)
        self.assertIn("-avoid_negative_ts", command)

    def test_live_ffmpeg_command_includes_rtsp_transport_for_rtsp_uri(self):
        command = _live_ffmpeg_command(
            "rtsp://example/stream",
            Path("/tmp/live/segment%03d.ts"),
            Path("/tmp/live/index.m3u8"),
        )

        self.assertIn("-rtsp_transport", command)

    def test_live_ffmpeg_command_includes_rtsp_transport_for_rtsps_uri(self):
        command = _live_ffmpeg_command(
            "rtsps://example/stream",
            Path("/tmp/live/segment%03d.ts"),
            Path("/tmp/live/index.m3u8"),
        )

        self.assertIn("-rtsp_transport", command)

    def test_live_ffmpeg_command_omits_rtsp_transport_for_http_uri(self):
        # ffmpeg hard-fails ("Option rtsp_transport not found") if this
        # RTSP-demuxer-only option is passed for a non-RTSP input protocol -
        # verified locally, not assumed.
        command = _live_ffmpeg_command(
            "http://127.0.0.1:18734/live/SERIAL123.ts",
            Path("/tmp/live/segment%03d.ts"),
            Path("/tmp/live/index.m3u8"),
        )

        self.assertNotIn("-rtsp_transport", command)

    def test_hls_unset_timestamp_warning_is_nonfatal(self):
        message = "[hls @ 0x55b196e0d0] Timestamps are unset in a packet for stream 0"

        self.assertTrue(_is_nonfatal_hls_warning(message))
        self.assertFalse(_is_nonfatal_hls_warning("Connection refused"))

    def test_live_message_hides_nonfatal_hls_warning(self):
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            manager._messages["camera-1"] = [
                "Starting live stream camera-1",
                "[hls @ 0x55b196e0d0] Timestamps are unset in a packet for stream 0",
            ]

            self.assertEqual(manager.message("camera-1"), "Starting live stream camera-1")


class DiagnoseStreamOpenFailureTests(unittest.TestCase):
    """Regression coverage for issue #34 (Tapo cameras failing with ffmpeg
    "Operation not permitted" under a Proxmox-hosted install): the diagnosis
    must tell the difference between the camera being unreachable and ffmpeg
    itself being unable to open a stream it can otherwise reach via TCP."""

    def test_returns_empty_string_when_the_uri_has_no_host(self):
        self.assertEqual(diagnose_stream_open_failure("not-a-uri"), "")

    def test_reports_environment_issue_when_tcp_connect_succeeds(self):
        with patch("app.tbc.live.socket.create_connection") as connect_mock:
            connect_mock.return_value.__enter__ = lambda self: self
            connect_mock.return_value.__exit__ = lambda *a: False
            diagnosis = diagnose_stream_open_failure("rtsp://user:pw@192.0.2.10:554/stream1")
        connect_mock.assert_called_once_with(("192.0.2.10", 554), timeout=3.0)
        self.assertIn("runtime environment", diagnosis)
        self.assertNotIn("user:pw", diagnosis)

    def test_reports_unreachable_when_tcp_connect_fails(self):
        with patch("app.tbc.live.socket.create_connection", side_effect=OSError("Connection refused")):
            diagnosis = diagnose_stream_open_failure("rtsp://192.0.2.10:554/stream1")
        self.assertIn("unreachable", diagnosis)
        self.assertIn("Connection refused", diagnosis)

    def test_defaults_to_port_554_when_the_uri_omits_one(self):
        with patch("app.tbc.live.socket.create_connection") as connect_mock:
            connect_mock.return_value.__enter__ = lambda self: self
            connect_mock.return_value.__exit__ = lambda *a: False
            diagnose_stream_open_failure("rtsp://192.0.2.10/stream1")
        connect_mock.assert_called_once_with(("192.0.2.10", 554), timeout=3.0)


class _FakeCrashedProcess:
    """A process that has already exited (unlike stop(), which is never called
    for a stream that crashed on its own - e.g. the camera dropped the RTSP
    session, or ffmpeg gave up decoding a corrupt stream)."""

    def poll(self):
        return 255


class LiveManagerRetryTests(unittest.TestCase):
    """Regression coverage for the "a crashed live stream never recovers on its
    own" bug: previously nothing ever called start() again once ffmpeg exited,
    so a tile stayed on 'failed'/'Waiting for stream' until an admin reopened
    the live page or clicked refresh - see should_retry()'s use in
    main._live_item_payload."""

    def test_never_started_stream_is_not_due_for_retry(self):
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            self.assertEqual(manager.status("camera-1"), "stopped")
            self.assertFalse(manager.should_retry("camera-1"))

    def test_running_stream_is_not_due_for_retry(self):
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            manager._processes["camera-1"] = _FakeRunningProcess()
            self.assertFalse(manager.should_retry("camera-1"))

    def test_crashed_stream_is_due_for_retry_once_cooldown_elapses(self):
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            manager._processes["camera-1"] = _FakeCrashedProcess()
            self.assertEqual(manager.status("camera-1"), "failed")
            manager._last_start_attempt["camera-1"] = time.monotonic() - (LiveManager.RETRY_COOLDOWN_SECONDS + 1)
            self.assertTrue(manager.should_retry("camera-1"))

    def test_crashed_stream_within_cooldown_is_not_retried_yet(self):
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            manager._processes["camera-1"] = _FakeCrashedProcess()
            manager._last_start_attempt["camera-1"] = time.monotonic()
            self.assertFalse(manager.should_retry("camera-1"))

    def test_crashed_stream_never_attempted_is_immediately_due(self):
        # _last_start_attempt only gets set by start() itself - a status()=="failed"
        # process with no recorded attempt (e.g. state loaded some other way)
        # should not be blocked from ever retrying.
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            manager._processes["camera-1"] = _FakeCrashedProcess()
            self.assertTrue(manager.should_retry("camera-1"))


class _FakeRunningProcess:
    def poll(self):
        return None


class _FakeFfmpegProcess:
    """Stands in for the subprocess.Popen handle _read_stderr reads from -
    stderr as an iterable of pre-baked lines, wait() returning a fixed exit
    code, matching how _read_stderr actually consumes a real ffmpeg process."""

    def __init__(self, stderr_lines: list[str], exit_code: int) -> None:
        self.stderr = iter(stderr_lines)
        self._exit_code = exit_code

    def wait(self) -> int:
        return self._exit_code


class ReadStderrGenerationTests(unittest.TestCase):
    """Regression coverage for issue #34's follow-up: diagnose_stream_open_failure
    blocks for up to a few seconds inside _read_stderr's background thread. If a
    newer start() for the same key happens while an older attempt's thread is
    still finishing up (ffmpeg can fail near-instantly, well within that
    window - confirmed by a real user's log showing two start attempts within
    the same second), the old thread must not go on to append its now-stale
    messages into what has since become a different generation's message list -
    otherwise the diagnosis for a superseded attempt can end up hiding the
    current attempt's own "ffmpeg exited" message, or vice versa.
    """

    def test_append_message_is_a_noop_for_a_stale_generation(self):
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            manager._generation["camera-1"] = 2
            manager._messages["camera-1"] = ["current generation's own message"]

            appended = manager._append_message("camera-1", 1, "stale message")

            self.assertFalse(appended)
            self.assertEqual(manager._messages["camera-1"], ["current generation's own message"])

    def test_append_message_succeeds_for_the_current_generation(self):
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            manager._generation["camera-1"] = 1
            manager._messages["camera-1"] = []

            appended = manager._append_message("camera-1", 1, "current message")

            self.assertTrue(appended)
            self.assertEqual(manager._messages["camera-1"], ["current message"])

    def test_stale_attempts_exit_message_does_not_overwrite_a_newer_attempt(self):
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            # Generation 2 has already started and posted its own message by
            # the time generation 1's (still-running) background thread gets
            # around to processing its own process exit.
            manager._generation["camera-1"] = 2
            manager._messages["camera-1"] = ["Starting live stream camera-1: rtsp://cam/2"]
            stale_process = _FakeFfmpegProcess([], exit_code=255)

            manager._read_stderr(
                "camera-1", stale_process, "rtsp://cam/1", manager.playlist_path("camera-1"), generation=1
            )

            self.assertEqual(manager._messages["camera-1"], ["Starting live stream camera-1: rtsp://cam/2"])

    def test_current_generation_exit_message_is_recorded_normally(self):
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            manager._generation["camera-1"] = 1
            manager._messages["camera-1"] = ["Starting live stream camera-1: rtsp://cam/1"]
            process = _FakeFfmpegProcess([], exit_code=255)

            with patch("app.tbc.live.diagnose_stream_open_failure", return_value=""):
                manager._read_stderr(
                    "camera-1", process, "rtsp://cam/1", manager.playlist_path("camera-1"), generation=1
                )

            self.assertIn("ffmpeg exited for camera-1 with code 255", manager._messages["camera-1"])

    def test_stale_generations_diagnosis_is_never_even_appended(self):
        with TemporaryDirectory() as temp_dir:
            manager = LiveManager(temp_dir)
            manager._generation["camera-1"] = 2
            manager._messages["camera-1"] = ["Starting live stream camera-1: rtsp://cam/2"]
            stale_process = _FakeFfmpegProcess([], exit_code=255)

            with patch("app.tbc.live.diagnose_stream_open_failure", return_value="Diagnosis: unreachable") as diag:
                manager._read_stderr(
                    "camera-1", stale_process, "rtsp://cam/1", manager.playlist_path("camera-1"), generation=1
                )

            # The exit-code append is checked first and fails the generation
            # check, so the (comparatively expensive) diagnosis probe never
            # even runs for an already-superseded attempt.
            diag.assert_not_called()
            self.assertEqual(manager._messages["camera-1"], ["Starting live stream camera-1: rtsp://cam/2"])


if __name__ == "__main__":
    unittest.main()
