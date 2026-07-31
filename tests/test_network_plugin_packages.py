import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from app.tbc.network_modules import normalize_account_configuration
from app.tbc.network_modules.packages import (
    NetworkPluginError,
    discover_plugin_packages,
    export_plugin_archive,
    install_plugin_archive,
    load_plugin_module,
    remove_external_plugin,
)
from app.tbc.network_modules.registry import (
    UnknownNetworkModuleError,
    get_network_module,
    list_network_module_registrations,
    reload_network_modules,
)
from app.tbc.plugin_requirements import MissingPluginRequirements


def plugin_archive(*, key="acme_network", wrapped=False, extra_files=None, requirements=None):
    manifest = {
        "schema_version": 1,
        "key": key,
        "label": "Acme Network",
        "version": "1.2.3",
        "description": "Test network controller",
        "entrypoint": "plugin.py",
        "default_port": 8443,
        "account_fields": [
            {"key": "host", "label": "Host", "type": "text", "required": True},
            {"key": "identifier", "label": "Username", "type": "text", "required": True},
            {"key": "secret", "label": "Password", "type": "password", "required": True},
        ],
    }
    if requirements is not None:
        manifest["requirements"] = requirements
    plugin_code = """
from tbc_network_api import NetworkAccountModule, NetworkDevice

class AcmeNetworkModule(NetworkAccountModule):
    async def discover_devices(self, account):
        return [NetworkDevice(mac_address="aa:bb:cc:dd:ee:ff", name="Acme Client")]

def create_module():
    return AcmeNetworkModule()
"""
    prefix = "acme-network-plugin/" if wrapped else ""
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(f"{prefix}manifest.json", json.dumps(manifest))
        bundle.writestr(f"{prefix}plugin.py", plugin_code)
        for name, value in extra_files or []:
            bundle.writestr(name, value)
    return output.getvalue()


class NetworkPluginPackageTests(unittest.TestCase):
    def test_no_builtin_plugins_ship_by_default(self):
        with tempfile.TemporaryDirectory() as external_path:
            packages = discover_plugin_packages(external_path)

        self.assertEqual(packages, ())

    def test_zip_plugin_can_be_installed_loaded_exported_and_removed(self):
        with tempfile.TemporaryDirectory() as external_path:
            package = install_plugin_archive(plugin_archive(wrapped=True), external_path)
            module = load_plugin_module(package)

            self.assertEqual(module.key, "acme_network")
            self.assertEqual(module.label, "Acme Network")
            self.assertEqual(module.default_port, 8443)
            self.assertEqual(
                [field.key for field in module.account_fields], ["host", "identifier", "secret"]
            )

            exported = export_plugin_archive(package)
            self.assertTrue(exported.startswith(b"PK"))
            package = install_plugin_archive(exported, external_path)
            self.assertEqual(load_plugin_module(package).key, "acme_network")

            remove_external_plugin("acme_network", external_path)
            self.assertFalse(package.path.exists())

    def test_account_fields_are_required(self):
        manifest = {
            "schema_version": 1,
            "key": "acme_network",
            "label": "Acme Network",
            "version": "1.0.0",
            "description": "",
            "entrypoint": "plugin.py",
        }
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest))
            bundle.writestr("plugin.py", "def create_module(): raise NotImplementedError")

        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(NetworkPluginError, "account_fields"):
                install_plugin_archive(output.getvalue(), external_path)

    def test_zip_slip_path_is_rejected(self):
        archive = plugin_archive(extra_files=[("../outside.py", "bad")])

        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(NetworkPluginError, "unsafe file path"):
                install_plugin_archive(archive, external_path)

    def test_invalid_zip_is_reported_as_plugin_error(self):
        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(NetworkPluginError, "not a valid ZIP"):
                install_plugin_archive(b"not a zip", external_path)

    def test_bundled_license_file_is_kept_after_install(self):
        archive = plugin_archive(wrapped=True, extra_files=[("acme-network-plugin/LICENSE", "MIT License...")])

        with tempfile.TemporaryDirectory() as external_path:
            package = install_plugin_archive(archive, external_path)

            self.assertTrue((package.path / "LICENSE").is_file())
            self.assertEqual((package.path / "LICENSE").read_text(), "MIT License...")

    def test_satisfied_requirement_installs_normally(self):
        # "unittest" ships with Python itself - not a real pip-installable
        # distribution, so this uses a genuinely always-present package
        # instead: the app's own already-installed "boto3".
        archive = plugin_archive(requirements=["boto3"])

        with tempfile.TemporaryDirectory() as external_path:
            package = install_plugin_archive(archive, external_path)

        self.assertEqual(package.manifest.requirements, ("boto3",))

    def test_missing_requirement_blocks_install_without_leaving_partial_files(self):
        archive = plugin_archive(requirements=["definitely-not-a-real-package-xyz==1.0"])

        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaises(MissingPluginRequirements) as ctx:
                install_plugin_archive(archive, external_path)
            self.assertEqual(ctx.exception.missing, ("definitely-not-a-real-package-xyz==1.0",))
            self.assertEqual(ctx.exception.plugin_label, "Acme Network")
            self.assertEqual(ctx.exception.plugin_kind, "network")
            self.assertEqual(ctx.exception.module_key, "acme_network")
            self.assertEqual(list(Path(external_path).iterdir()), [])

    def test_normalize_account_configuration_validates_required_fields(self):
        with tempfile.TemporaryDirectory() as external_path:
            package = install_plugin_archive(plugin_archive(), external_path)
            module = load_plugin_module(package)

        config = normalize_account_configuration(
            module.account_fields, {"host": "10.0.0.1", "identifier": "admin", "secret": "hunter2"}
        )
        self.assertEqual(config["host"], "10.0.0.1")


class NetworkModuleRegistryTests(unittest.TestCase):
    def tearDown(self):
        reload_network_modules()

    def test_unknown_module_raises(self):
        with self.assertRaises(UnknownNetworkModuleError):
            get_network_module("does-not-exist")

    def test_registry_reflects_installed_plugins(self):
        from app.tbc.config import load_settings

        with tempfile.TemporaryDirectory() as external_path:
            install_plugin_archive(plugin_archive(wrapped=True), external_path)
            patched_settings = replace(load_settings(), network_modules_path=external_path)

            with patch("app.tbc.network_modules.registry.load_settings", return_value=patched_settings):
                reload_network_modules()
                registrations = list_network_module_registrations()

        self.assertEqual([r.module.key for r in registrations], ["acme_network"])
        self.assertEqual(registrations[0].origin, "uploaded")


if __name__ == "__main__":
    unittest.main()
