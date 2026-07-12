import json
import tempfile
import unittest
import zipfile
from io import BytesIO

from app.tbc.cloud_modules import CloudAuthType, normalize_account_configuration
from app.tbc.cloud_modules.packages import (
    CloudPluginError,
    discover_plugin_packages,
    export_plugin_archive,
    install_plugin_archive,
    load_plugin_module,
    remove_external_plugin,
)


def plugin_archive(*, key="acme_cloud", wrapped=False, extra_files=None):
    manifest = {
        "schema_version": 1,
        "key": key,
        "label": "Acme Cloud",
        "version": "1.2.3",
        "description": "Test-Cloud-Konto",
        "entrypoint": "plugin.py",
        "auth_type": "token",
        "identifier_label": "Konto-ID",
        "secret_label": "API-Schlüssel",
        "requires_host": False,
        "default_port": 8443,
    }
    plugin_code = """
from tbc_cloud_api import CloudAccountModule, CloudDevice

class AcmeCloudModule(CloudAccountModule):
    async def test_connection(self, account):
        return "ok"

    async def discover_devices(self, account):
        return [CloudDevice(external_id="1", name="Acme Cam")]

def create_module():
    return AcmeCloudModule()
"""
    prefix = "acme-cloud-plugin/" if wrapped else ""
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(f"{prefix}manifest.json", json.dumps(manifest))
        bundle.writestr(f"{prefix}plugin.py", plugin_code)
        for name, value in extra_files or []:
            bundle.writestr(name, value)
    return output.getvalue()


class CloudPluginPackageTests(unittest.TestCase):
    def test_builtin_plugins_have_exportable_manifests(self):
        with tempfile.TemporaryDirectory() as external_path:
            packages = discover_plugin_packages(external_path)

        self.assertEqual([package.manifest.key for package in packages], ["eufy", "unifi_protect"])
        for package in packages:
            archive = export_plugin_archive(package)
            with zipfile.ZipFile(BytesIO(archive)) as bundle:
                self.assertIn("manifest.json", bundle.namelist())
                self.assertIn("plugin.py", bundle.namelist())
                self.assertIn("module.py", bundle.namelist())

    def test_builtin_unifi_protect_manifest_fields(self):
        with tempfile.TemporaryDirectory() as external_path:
            packages = discover_plugin_packages(external_path)

        unifi = next(package for package in packages if package.manifest.key == "unifi_protect")
        self.assertEqual(unifi.manifest.auth_type, CloudAuthType.CREDENTIALS)
        self.assertTrue(unifi.manifest.requires_host)
        self.assertEqual(unifi.manifest.default_port, 443)
        self.assertEqual(
            [field.key for field in unifi.manifest.account_fields],
            ["host", "port", "identifier", "secret", "verify_ssl"],
        )

    def test_builtin_eufy_manifest_owns_its_account_fields(self):
        with tempfile.TemporaryDirectory() as external_path:
            packages = discover_plugin_packages(external_path)

        eufy = next(package for package in packages if package.manifest.key == "eufy")
        self.assertEqual(
            [field.key for field in eufy.manifest.account_fields],
            [
                "email",
                "password",
                "country",
                "verification_code",
                "rtsp_username",
                "rtsp_password",
            ],
        )
        verification_field = next(
            field for field in eufy.manifest.account_fields if field.key == "verification_code"
        )
        self.assertTrue(verification_field.transient)
        config = normalize_account_configuration(
            eufy.manifest.account_fields,
            {"email": "user@example.com", "password": "secret"},
        )
        self.assertEqual(config["country"], "DE")
        self.assertEqual(config["rtsp_username"], "")

    def test_zip_plugin_can_be_installed_loaded_exported_and_removed(self):
        with tempfile.TemporaryDirectory() as external_path:
            package = install_plugin_archive(plugin_archive(wrapped=True), external_path)
            module = load_plugin_module(package)

            self.assertEqual(module.key, "acme_cloud")
            self.assertEqual(module.label, "Acme Cloud")
            self.assertEqual(module.auth_type, CloudAuthType.TOKEN)
            self.assertEqual(module.identifier_label, "Konto-ID")
            self.assertEqual(module.default_port, 8443)
            self.assertFalse(module.requires_host)

            exported = export_plugin_archive(package)
            self.assertTrue(exported.startswith(b"PK"))
            package = install_plugin_archive(exported, external_path)
            self.assertEqual(load_plugin_module(package).key, "acme_cloud")

            remove_external_plugin("acme_cloud", external_path)
            self.assertFalse(package.path.exists())

    def test_zip_slip_path_is_rejected(self):
        archive = plugin_archive(extra_files=[("../outside.py", "bad")])

        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(CloudPluginError, "unsicheren Dateipfad"):
                install_plugin_archive(archive, external_path)

    def test_builtin_plugin_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(CloudPluginError, "nicht überschrieben"):
                install_plugin_archive(plugin_archive(key="unifi_protect"), external_path)

    def test_invalid_zip_is_reported_as_plugin_error(self):
        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(CloudPluginError, "kein gültiges ZIP"):
                install_plugin_archive(b"not a zip", external_path)


if __name__ == "__main__":
    unittest.main()
