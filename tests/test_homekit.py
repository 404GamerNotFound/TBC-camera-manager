import json
import sys
import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from app.tbc import database
from app.tbc.homekit import (
    HomeKitManager,
    _homekit_ffmpeg_command,
    detect_host_networking_gap,
)


class HomekitFfmpegCommandTests(unittest.TestCase):
    def _stream_config(self, **overrides):
        config = {
            "width": 1280,
            "height": 720,
            "fps": 30,
            "v_ssrc": 12345,
            "v_srtp_key": "base64key==",
            "address": "192.168.1.50",
            "v_port": 51000,
        }
        config.update(overrides)
        return config

    def test_includes_srtp_output_with_negotiated_params(self):
        command = _homekit_ffmpeg_command("rtsp://cam/stream", self._stream_config())

        self.assertIn("-srtp_out_suite", command)
        self.assertIn("AES_CM_128_HMAC_SHA1_80", command)
        self.assertIn("base64key==", command)
        self.assertIn("srtp://192.168.1.50:51000?rtcpport=51000&localrtcpport=51000&pkt_size=1378", command)

    def test_video_only_no_audio(self):
        command = _homekit_ffmpeg_command("rtsp://cam/stream", self._stream_config())

        self.assertIn("-an", command)

    def test_transcodes_to_h264_baseline(self):
        command = _homekit_ffmpeg_command("rtsp://cam/stream", self._stream_config())

        self.assertIn("libx264", command)
        self.assertIn("baseline", command)

    def test_rtsp_transport_only_added_for_rtsp_scheme(self):
        rtsp_command = _homekit_ffmpeg_command("rtsp://cam/stream", self._stream_config())
        http_command = _homekit_ffmpeg_command("http://cam/stream.ts", self._stream_config())

        self.assertIn("-rtsp_transport", rtsp_command)
        self.assertNotIn("-rtsp_transport", http_command)

    def test_missing_max_bitrate_falls_back_to_a_default(self):
        config = self._stream_config()
        command = _homekit_ffmpeg_command("rtsp://cam/stream", config)

        bitrate_index = command.index("-b:v") + 1
        self.assertEqual(command[bitrate_index], "300k")

    def test_uses_negotiated_max_bitrate_when_present(self):
        config = self._stream_config(v_max_bitrate=800)
        command = _homekit_ffmpeg_command("rtsp://cam/stream", config)

        bitrate_index = command.index("-b:v") + 1
        self.assertEqual(command[bitrate_index], "800k")


class DetectHostNetworkingGapTests(unittest.TestCase):
    def test_docker_bridge_address_is_flagged(self):
        with patch("app.tbc.homekit.pyhap_util.get_local_address", return_value="172.18.0.5"):
            with patch("app.tbc.homekit.Path") as path_cls:
                path_cls.return_value.exists.return_value = True
                result = detect_host_networking_gap()

        self.assertEqual(result, {"address": "172.18.0.5", "likely_bridge_networking": True})

    def test_lan_address_is_not_flagged_even_inside_docker(self):
        with patch("app.tbc.homekit.pyhap_util.get_local_address", return_value="192.168.1.42"):
            with patch("app.tbc.homekit.Path") as path_cls:
                path_cls.return_value.exists.return_value = True
                result = detect_host_networking_gap()

        self.assertEqual(result, {"address": "192.168.1.42", "likely_bridge_networking": False})

    def test_bridge_range_address_outside_docker_is_not_flagged(self):
        # The heuristic only fires when both signals agree - a legitimate
        # 172.16.0.0/12 LAN outside a container must not be flagged.
        with patch("app.tbc.homekit.pyhap_util.get_local_address", return_value="172.20.0.5"):
            with patch("app.tbc.homekit.Path") as path_cls:
                path_cls.return_value.exists.return_value = False
                result = detect_host_networking_gap()

        self.assertFalse(result["likely_bridge_networking"])

    def test_address_resolution_failure_is_handled(self):
        with patch("app.tbc.homekit.pyhap_util.get_local_address", side_effect=OSError("no route")):
            result = detect_host_networking_gap()

        self.assertEqual(result, {"address": None, "likely_bridge_networking": False})


class HomeKitManagerStartStopTests(unittest.TestCase):
    def _fake_process(self):
        process = MagicMock()
        process.poll.return_value = None
        process.stderr = iter([])
        process.wait.return_value = 0
        return process

    def test_start_raises_when_ffmpeg_missing(self):
        with TemporaryDirectory() as temp_dir:
            manager = HomeKitManager(temp_dir, 51826)
            with patch("shutil.which", return_value=None):
                with self.assertRaises(RuntimeError):
                    manager.start([{"aid": 2, "name": "Cam", "stream_uri": "rtsp://cam", "snapshot_path": None}], "123-45-678")

    def test_start_writes_worker_config_and_spawns_subprocess(self):
        with TemporaryDirectory() as temp_dir:
            manager = HomeKitManager(temp_dir, 51826)
            cameras = [{"aid": 2, "name": "Front", "stream_uri": "rtsp://cam/stream", "snapshot_path": None}]

            with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                with patch("subprocess.Popen", return_value=self._fake_process()) as popen:
                    manager.start(cameras, "123-45-678")

            command = popen.call_args.args[0]
            self.assertEqual(command[0], sys.executable)
            self.assertEqual(command[1:3], ["-m", "app.tbc.homekit_worker"])
            config_path = Path(command[3])
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["port"], 51826)
            self.assertEqual(config["pincode"], "123-45-678")
            self.assertEqual(config["cameras"], cameras)
            self.assertEqual(manager.status(), "running")

    def test_start_is_idempotent_while_already_running(self):
        with TemporaryDirectory() as temp_dir:
            manager = HomeKitManager(temp_dir, 51826)
            cameras = [{"aid": 2, "name": "Front", "stream_uri": "rtsp://cam/stream", "snapshot_path": None}]

            with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                with patch("subprocess.Popen", return_value=self._fake_process()) as popen:
                    manager.start(cameras, "123-45-678")
                    manager.start(cameras, "123-45-678")

            self.assertEqual(popen.call_count, 1)

    def test_stop_terminates_running_process(self):
        with TemporaryDirectory() as temp_dir:
            manager = HomeKitManager(temp_dir, 51826)
            process = self._fake_process()
            cameras = [{"aid": 2, "name": "Front", "stream_uri": "rtsp://cam/stream", "snapshot_path": None}]

            with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                with patch("subprocess.Popen", return_value=process):
                    manager.start(cameras, "123-45-678")

            manager.stop()

            process.terminate.assert_called_once()
            self.assertEqual(manager.status(), "stopped")

    def test_stop_without_start_is_a_no_op(self):
        with TemporaryDirectory() as temp_dir:
            manager = HomeKitManager(temp_dir, 51826)
            manager.stop()
            self.assertEqual(manager.status(), "stopped")


class HomeKitManagerPairingInfoTests(unittest.TestCase):
    def test_pairing_info_defaults_when_nothing_persisted_yet(self):
        with TemporaryDirectory() as temp_dir:
            manager = HomeKitManager(temp_dir, 51826)
            self.assertEqual(manager.pairing_info(), {"paired": False, "pincode": None, "xhm_uri": None})

    def test_pairing_info_reads_paired_state_and_status_file(self):
        with TemporaryDirectory() as temp_dir:
            manager = HomeKitManager(temp_dir, 51826)
            Path(temp_dir).mkdir(parents=True, exist_ok=True)
            (Path(temp_dir) / "accessory.state").write_text(
                json.dumps({"paired_clients": {"11111111-1111-1111-1111-111111111111": "aa"}}), encoding="utf-8"
            )
            (Path(temp_dir) / "status.json").write_text(
                json.dumps({"pincode": "123-45-678", "xhm_uri": "X-HM://something"}), encoding="utf-8"
            )

            info = manager.pairing_info()

        self.assertTrue(info["paired"])
        self.assertEqual(info["pincode"], "123-45-678")
        self.assertEqual(info["xhm_uri"], "X-HM://something")

    def test_pairing_info_treats_empty_paired_clients_as_unpaired(self):
        with TemporaryDirectory() as temp_dir:
            manager = HomeKitManager(temp_dir, 51826)
            Path(temp_dir).mkdir(parents=True, exist_ok=True)
            (Path(temp_dir) / "accessory.state").write_text(json.dumps({"paired_clients": {}}), encoding="utf-8")

            self.assertFalse(manager.pairing_info()["paired"])

    def test_reset_pairing_deletes_persisted_state(self):
        with TemporaryDirectory() as temp_dir:
            manager = HomeKitManager(temp_dir, 51826)
            Path(temp_dir).mkdir(parents=True, exist_ok=True)
            (Path(temp_dir) / "accessory.state").write_text("{}", encoding="utf-8")
            (Path(temp_dir) / "status.json").write_text("{}", encoding="utf-8")

            manager.reset_pairing()

            self.assertFalse((Path(temp_dir) / "accessory.state").exists())
            self.assertFalse((Path(temp_dir) / "status.json").exists())

    def test_reset_pairing_without_existing_files_is_a_no_op(self):
        with TemporaryDirectory() as temp_dir:
            manager = HomeKitManager(temp_dir, 51826)
            manager.reset_pairing()  # must not raise


class HomekitDatabaseTests(unittest.TestCase):
    def test_settings_default_and_generate_a_pincode_on_first_read(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            settings = database.get_homekit_settings(handle.name)

        self.assertFalse(settings["enabled"])
        self.assertRegex(settings["pincode"], r"^\d{3}-\d{2}-\d{3}$")

    def test_pincode_is_stable_across_reads(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            first = database.get_homekit_settings(handle.name)["pincode"]
            second = database.get_homekit_settings(handle.name)["pincode"]

        self.assertEqual(first, second)

    def test_set_homekit_enabled_round_trips(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            database.set_homekit_enabled(handle.name, True)
            self.assertTrue(database.get_homekit_settings(handle.name)["enabled"])
            database.set_homekit_enabled(handle.name, False)
            self.assertFalse(database.get_homekit_settings(handle.name)["enabled"])

    def _create_camera(self, database_path: str, name: str) -> int:
        return database.create_camera(
            database_path,
            name=name,
            host="192.0.2.10",
            onvif_port=8000,
            http_port=80,
            username="admin",
            password="secret",
        )

    def test_camera_aids_start_at_two_and_are_unique(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            first = self._create_camera(handle.name, "Front")
            second = self._create_camera(handle.name, "Back")
            database.set_homekit_camera_ids(handle.name, [first, second])

            aids = database.get_homekit_camera_aids(handle.name)

        self.assertEqual(set(aids.values()), {2, 3})

    def test_aid_is_preserved_across_resaves_for_a_still_selected_camera(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            first = self._create_camera(handle.name, "Front")
            second = self._create_camera(handle.name, "Back")
            database.set_homekit_camera_ids(handle.name, [first, second])
            original_aid = database.get_homekit_camera_aids(handle.name)[second]

            database.set_homekit_camera_ids(handle.name, [second])

            self.assertEqual(database.get_homekit_camera_aids(handle.name)[second], original_aid)

    def test_re_added_camera_gets_a_fresh_aid_not_its_old_one(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            first = self._create_camera(handle.name, "Front")
            second = self._create_camera(handle.name, "Back")
            database.set_homekit_camera_ids(handle.name, [first, second])
            original_first_aid = database.get_homekit_camera_aids(handle.name)[first]

            database.set_homekit_camera_ids(handle.name, [second])
            database.set_homekit_camera_ids(handle.name, [second, first])

            self.assertNotEqual(database.get_homekit_camera_aids(handle.name)[first], original_first_aid)

    def test_deleting_a_camera_removes_it_from_the_selection(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            database.initialize(handle.name)
            camera_id = self._create_camera(handle.name, "Front")
            database.set_homekit_camera_ids(handle.name, [camera_id])

            database.delete_camera(handle.name, camera_id)

            self.assertEqual(database.get_homekit_camera_aids(handle.name), {})


if __name__ == "__main__":
    unittest.main()
