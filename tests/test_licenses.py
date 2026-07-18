import tempfile
import unittest
import zipfile
from dataclasses import replace
from io import BytesIO
from unittest.mock import patch

from app.tbc.config import load_settings
from app.tbc.licenses import list_plugin_licenses
from app.tbc.network_modules.packages import install_plugin_archive
from app.tbc.network_modules.registry import list_network_module_registrations, reload_network_modules


def _network_plugin_archive(*, with_license: bool) -> bytes:
    manifest = """{
      "schema_version": 1,
      "key": "acme_network",
      "label": "Acme Network",
      "version": "1.0.0",
      "description": "",
      "entrypoint": "plugin.py",
      "account_fields": [{"key": "host", "label": "Host", "type": "text", "required": true}]
    }"""
    plugin_code = """
from tbc_network_api import NetworkAccountModule

class AcmeNetworkModule(NetworkAccountModule):
    async def discover_devices(self, account):
        return []

def create_module():
    return AcmeNetworkModule()
"""
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("acme/manifest.json", manifest)
        bundle.writestr("acme/plugin.py", plugin_code)
        if with_license:
            bundle.writestr("acme/LICENSE", "MIT License...\n\nCopyright (c) Acme")
    return output.getvalue()


class PluginLicenseDiscoveryTests(unittest.TestCase):
    def tearDown(self):
        reload_network_modules()

    def test_builtin_camera_and_cloud_plugins_have_no_bundled_license(self):
        # None of the modules loaded by default (rtsp_only, standard_onvif, and
        # any cloud plugins) ship a LICENSE file, so the scan should find nothing
        # without needing to install anything - a sanity check that this doesn't
        # spuriously match unrelated files.
        entries = list_plugin_licenses()

        self.assertEqual([e for e in entries if e["kind"] in ("camera", "cloud")], [])

    def test_installed_network_plugin_with_license_is_discovered(self):
        with tempfile.TemporaryDirectory() as external_path:
            install_plugin_archive(_network_plugin_archive(with_license=True), external_path)
            patched_settings = replace(load_settings(), network_modules_path=external_path)

            with patch("app.tbc.network_modules.registry.load_settings", return_value=patched_settings):
                reload_network_modules()
                self.assertEqual([r.module.key for r in list_network_module_registrations()], ["acme_network"])
                entries = list_plugin_licenses()

        network_entries = [e for e in entries if e["kind"] == "network"]
        self.assertEqual(len(network_entries), 1)
        entry = network_entries[0]
        self.assertEqual(entry["label"], "Acme Network")
        self.assertEqual(entry["key"], "acme_network")
        self.assertEqual(entry["kind_label"], "Network provider")
        self.assertIn("MIT License", entry["license_text"])

    def test_installed_network_plugin_without_license_is_not_discovered(self):
        with tempfile.TemporaryDirectory() as external_path:
            install_plugin_archive(_network_plugin_archive(with_license=False), external_path)
            patched_settings = replace(load_settings(), network_modules_path=external_path)

            with patch("app.tbc.network_modules.registry.load_settings", return_value=patched_settings):
                reload_network_modules()
                entries = list_plugin_licenses()

        self.assertEqual([e for e in entries if e["kind"] == "network"], [])


if __name__ == "__main__":
    unittest.main()
