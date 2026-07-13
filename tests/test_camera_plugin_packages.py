import json
import tempfile
import unittest
import zipfile
from io import BytesIO

from app.tbc.camera_modules import CameraCapability
from app.tbc.camera_modules.packages import (
    CameraPluginError,
    discover_plugin_packages,
    export_plugin_archive,
    install_plugin_archive,
    load_plugin_module,
    remove_external_plugin,
)


def plugin_archive(*, key="acme", wrapped=False, extra_files=None):
    manifest = {
        "schema_version": 1,
        "key": key,
        "label": "Acme Camera",
        "version": "1.2.3",
        "description": "Testkamera",
        "entrypoint": "plugin.py",
        "capabilities": ["live"],
        "ports": {"onvif": 9000, "http": 8080, "rtsp": 8554},
    }
    plugin_code = """
from tbc_camera_api import CameraModule, CameraSnapshot

class AcmeModule(CameraModule):
    async def probe(self, camera):
        return CameraSnapshot(status="ok", message="Acme")

def create_module():
    return AcmeModule()
"""
    prefix = "acme-plugin/" if wrapped else ""
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(f"{prefix}manifest.json", json.dumps(manifest))
        bundle.writestr(f"{prefix}plugin.py", plugin_code)
        for name, value in extra_files or []:
            bundle.writestr(name, value)
    return output.getvalue()


class CameraPluginPackageTests(unittest.TestCase):
    def test_builtin_plugins_have_exportable_manifests_and_detection_config(self):
        with tempfile.TemporaryDirectory() as external_path:
            packages = discover_plugin_packages(external_path)

        self.assertEqual(
            [package.manifest.key for package in packages],
            [
                "rtsp_only",
                "standard_onvif",
            ],
        )
        for package in packages:
            archive = export_plugin_archive(package)
            with zipfile.ZipFile(BytesIO(archive)) as bundle:
                self.assertIn("manifest.json", bundle.namelist())
                self.assertIn("plugin.py", bundle.namelist())
                self.assertIn("detections.json", bundle.namelist())

    def test_builtin_plugin_export_includes_its_own_device_specific_implementation(self):
        """Builtin plugins are encapsulated exactly like external ones: the exported
        archive contains their manufacturer-specific code, not just the manifest
        shim, because that code physically lives inside the plugin directory."""
        with tempfile.TemporaryDirectory() as external_path:
            packages = discover_plugin_packages(external_path)

        standard_onvif = next(package for package in packages if package.manifest.key == "standard_onvif")
        archive = export_plugin_archive(standard_onvif)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            names = set(bundle.namelist())
        self.assertTrue({"module.py", "service.py", "catalog.py", "control.py"} <= names)

    def test_zip_plugin_can_be_installed_loaded_exported_and_removed(self):
        with tempfile.TemporaryDirectory() as external_path:
            package = install_plugin_archive(plugin_archive(wrapped=True), external_path)
            module = load_plugin_module(package)

            self.assertEqual(module.key, "acme")
            self.assertEqual(module.label, "Acme Camera")
            self.assertEqual(module.default_onvif_port, 9000)
            self.assertTrue(module.supports(CameraCapability.LIVE))
            exported = export_plugin_archive(package)
            self.assertTrue(exported.startswith(b"PK"))
            package = install_plugin_archive(exported, external_path)
            self.assertEqual(load_plugin_module(package).key, "acme")

            remove_external_plugin("acme", external_path)
            self.assertFalse(package.path.exists())

    def test_zip_slip_path_is_rejected(self):
        archive = plugin_archive(extra_files=[("../outside.py", "bad")])

        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(CameraPluginError, "unsicheren Dateipfad"):
                install_plugin_archive(archive, external_path)

    def test_builtin_plugin_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(CameraPluginError, "nicht überschrieben"):
                install_plugin_archive(plugin_archive(key="standard_onvif"), external_path)

    def test_invalid_zip_is_reported_as_plugin_error(self):
        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(CameraPluginError, "kein gültiges ZIP"):
                install_plugin_archive(b"not a zip", external_path)


if __name__ == "__main__":
    unittest.main()
