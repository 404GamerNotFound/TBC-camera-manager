import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.tbc.detection.model_provisioning import download_model_if_missing
from app.tbc.detection.plugin_models import resolve_plugin_model


class FakeModule:
    def __init__(self, key):
        self.key = key


class FakePackage:
    def __init__(self, path):
        self.path = path


class FakeRegistration:
    def __init__(self, key, package=None):
        self.module = FakeModule(key)
        self.package = package


class DownloadModelIfMissingTests(unittest.TestCase):
    def test_downloads_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.onnx"
            source.write_bytes(b"weights")
            destination = Path(tmp) / "cache" / "model.onnx"
            ok = download_model_if_missing(f"file://{source}", destination)
            self.assertTrue(ok)
            self.assertEqual(destination.read_bytes(), b"weights")

    def test_skips_download_when_already_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "model.onnx"
            destination.write_bytes(b"cached")
            ok = download_model_if_missing("file:///does/not/exist.onnx", destination)
            self.assertTrue(ok)
            self.assertEqual(destination.read_bytes(), b"cached")

    def test_returns_false_on_failed_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "model.onnx"
            ok = download_model_if_missing("file:///does/not/exist.onnx", destination)
            self.assertFalse(ok)
            self.assertFalse(destination.exists())


class ResolvePluginModelTests(unittest.TestCase):
    def test_returns_none_without_module_key(self):
        self.assertIsNone(resolve_plugin_model(None, cache_root=Path(tempfile.gettempdir())))

    def test_returns_none_when_module_has_no_package(self):
        with patch(
            "app.tbc.detection.plugin_models.list_camera_module_registrations",
            return_value=[FakeRegistration("standard_onvif")],
        ):
            with tempfile.TemporaryDirectory() as tmp:
                self.assertIsNone(resolve_plugin_model("standard_onvif", cache_root=Path(tmp)))

    def test_returns_none_when_package_has_no_detection_model_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "package"
            package_dir.mkdir()
            registrations = [FakeRegistration("reolink", FakePackage(package_dir))]
            with patch("app.tbc.detection.plugin_models.list_camera_module_registrations", return_value=registrations):
                self.assertIsNone(resolve_plugin_model("reolink", cache_root=Path(tmp) / "cache"))

    def test_resolves_and_downloads_bundled_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "package"
            package_dir.mkdir()
            model_source = Path(tmp) / "model.onnx"
            model_source.write_bytes(b"plugin weights")
            metadata = {"model_url": f"file://{model_source}", "input_size": [300, 300], "classes": {"1": "person"}}
            (package_dir / "detection_model.json").write_text(json.dumps(metadata), encoding="utf-8")
            registrations = [FakeRegistration("reolink", FakePackage(package_dir))]
            cache_root = Path(tmp) / "cache"
            with patch("app.tbc.detection.plugin_models.list_camera_module_registrations", return_value=registrations):
                result = resolve_plugin_model("reolink", cache_root=cache_root)
            self.assertIsNotNone(result)
            model_path, metadata_path = result
            self.assertEqual(model_path.read_bytes(), b"plugin weights")
            self.assertEqual(json.loads(metadata_path.read_text())["model_url"], f"file://{model_source}")

    def test_is_case_insensitive_on_module_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "package"
            package_dir.mkdir()
            model_source = Path(tmp) / "model.onnx"
            model_source.write_bytes(b"weights")
            (package_dir / "detection_model.json").write_text(
                json.dumps({"model_url": f"file://{model_source}"}), encoding="utf-8"
            )
            registrations = [FakeRegistration("Reolink", FakePackage(package_dir))]
            with patch("app.tbc.detection.plugin_models.list_camera_module_registrations", return_value=registrations):
                result = resolve_plugin_model("REOLINK", cache_root=Path(tmp) / "cache")
            self.assertIsNotNone(result)

    def test_redownloads_when_metadata_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "package"
            package_dir.mkdir()
            model_v1 = Path(tmp) / "v1.onnx"
            model_v1.write_bytes(b"v1")
            model_v2 = Path(tmp) / "v2.onnx"
            model_v2.write_bytes(b"v2")
            metadata_file = package_dir / "detection_model.json"
            metadata_file.write_text(json.dumps({"model_url": f"file://{model_v1}"}), encoding="utf-8")
            registrations = [FakeRegistration("reolink", FakePackage(package_dir))]
            cache_root = Path(tmp) / "cache"
            with patch("app.tbc.detection.plugin_models.list_camera_module_registrations", return_value=registrations):
                first = resolve_plugin_model("reolink", cache_root=cache_root)
                self.assertEqual(first[0].read_bytes(), b"v1")
                metadata_file.write_text(json.dumps({"model_url": f"file://{model_v2}"}), encoding="utf-8")
                second = resolve_plugin_model("reolink", cache_root=cache_root)
                self.assertEqual(second[0].read_bytes(), b"v2")


if __name__ == "__main__":
    unittest.main()
