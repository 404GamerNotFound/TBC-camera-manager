import tempfile
import unittest
from pathlib import Path

from app.tbc.plugin_testing import run_plugin_tests


class RunPluginTestsTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_without_tests_directory_is_reported_as_not_run(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            result = await run_plugin_tests(Path(plugin_dir), "camera")

        self.assertFalse(result.ran)
        self.assertFalse(result.passed)
        self.assertIn("no tests", result.summary)

    async def test_passing_tests_are_reported_as_passed(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            tests_dir = Path(plugin_dir) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_ok.py").write_text("def test_ok():\n    assert True\n")

            result = await run_plugin_tests(Path(plugin_dir), "camera")

        self.assertTrue(result.ran)
        self.assertTrue(result.passed)
        self.assertIn("passed", result.summary)

    async def test_failing_tests_are_reported_as_failed(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            tests_dir = Path(plugin_dir) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_bad.py").write_text("def test_bad():\n    assert False\n")

            result = await run_plugin_tests(Path(plugin_dir), "cloud")

        self.assertTrue(result.ran)
        self.assertFalse(result.passed)
        self.assertIn("failed", result.summary)

    async def test_empty_tests_directory_is_reported_as_not_run(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            (Path(plugin_dir) / "tests").mkdir()

            result = await run_plugin_tests(Path(plugin_dir), "camera")

        self.assertFalse(result.ran)

    async def test_camera_plugin_test_can_import_the_tbc_camera_api_facade(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            tests_dir = Path(plugin_dir) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_facade.py").write_text(
                "def test_facade_importable():\n"
                "    from tbc_camera_api import CameraModule, CameraSnapshot\n"
                "    assert CameraModule is not None\n"
                "    assert CameraSnapshot is not None\n"
            )

            result = await run_plugin_tests(Path(plugin_dir), "camera")

        self.assertTrue(result.ran, result.output)
        self.assertTrue(result.passed, result.output)

    async def test_cloud_plugin_test_can_import_the_tbc_cloud_api_facade(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            tests_dir = Path(plugin_dir) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_facade.py").write_text(
                "def test_facade_importable():\n"
                "    from tbc_cloud_api import CloudAccountModule, CloudDevice\n"
                "    assert CloudAccountModule is not None\n"
                "    assert CloudDevice is not None\n"
            )

            result = await run_plugin_tests(Path(plugin_dir), "cloud")

        self.assertTrue(result.ran, result.output)
        self.assertTrue(result.passed, result.output)


if __name__ == "__main__":
    unittest.main()
