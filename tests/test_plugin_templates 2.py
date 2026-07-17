import tempfile
import unittest

from app.tbc.camera_modules.packages import install_plugin_archive as install_camera_plugin
from app.tbc.camera_modules.packages import load_plugin_module as load_camera_plugin
from app.tbc.cloud_modules.packages import install_plugin_archive as install_cloud_plugin
from app.tbc.cloud_modules.packages import load_plugin_module as load_cloud_plugin
from app.tbc.plugin_templates import (
    build_camera_plugin_template,
    build_cloud_plugin_template,
    build_design_theme_template,
)
from app.tbc.plugin_testing import run_plugin_tests
from app.tbc.themes.packages import install_theme_archive


class CameraPluginTemplateTests(unittest.IsolatedAsyncioTestCase):
    async def test_template_installs_and_its_own_tests_pass(self):
        with tempfile.TemporaryDirectory() as external_path:
            package = install_camera_plugin(build_camera_plugin_template(), external_path)
            module = load_camera_plugin(package)

            self.assertEqual(module.key, "acme_camera")

            result = await run_plugin_tests(package.path, "camera")

        self.assertTrue(result.ran, result.output)
        self.assertTrue(result.passed, result.output)


class CloudPluginTemplateTests(unittest.IsolatedAsyncioTestCase):
    async def test_template_installs_and_its_own_tests_pass(self):
        with tempfile.TemporaryDirectory() as external_path:
            package = install_cloud_plugin(build_cloud_plugin_template(), external_path)
            module = load_cloud_plugin(package)

            self.assertEqual(module.key, "acme_cloud")

            result = await run_plugin_tests(package.path, "cloud")

        self.assertTrue(result.ran, result.output)
        self.assertTrue(result.passed, result.output)


class DesignThemeTemplateTests(unittest.TestCase):
    def test_template_installs(self):
        with tempfile.TemporaryDirectory() as external_path:
            package = install_theme_archive(build_design_theme_template(), external_path)

        self.assertEqual(package.manifest.key, "acme_design")
        self.assertEqual(package.manifest.stylesheet, "styles.css")


if __name__ == "__main__":
    unittest.main()
