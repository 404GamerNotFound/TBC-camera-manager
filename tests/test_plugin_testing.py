import tempfile
import unittest
from pathlib import Path

from app.tbc.plugin_testing import run_plugin_tests


class RunPluginTestsTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_without_tests_directory_is_reported_as_not_run(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            result = await run_plugin_tests(Path(plugin_dir))

        self.assertFalse(result.ran)
        self.assertFalse(result.passed)
        self.assertIn("Keine Tests", result.summary)

    async def test_passing_tests_are_reported_as_passed(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            tests_dir = Path(plugin_dir) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_ok.py").write_text("def test_ok():\n    assert True\n")

            result = await run_plugin_tests(Path(plugin_dir))

        self.assertTrue(result.ran)
        self.assertTrue(result.passed)
        self.assertIn("passed", result.summary)

    async def test_failing_tests_are_reported_as_failed(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            tests_dir = Path(plugin_dir) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_bad.py").write_text("def test_bad():\n    assert False\n")

            result = await run_plugin_tests(Path(plugin_dir))

        self.assertTrue(result.ran)
        self.assertFalse(result.passed)
        self.assertIn("failed", result.summary)

    async def test_empty_tests_directory_is_reported_as_not_run(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            (Path(plugin_dir) / "tests").mkdir()

            result = await run_plugin_tests(Path(plugin_dir))

        self.assertFalse(result.ran)


if __name__ == "__main__":
    unittest.main()
