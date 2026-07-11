import tempfile
import unittest
import sqlite3
from unittest.mock import patch

from app.tbc import database
from app.tbc.camera_modules import CameraCapability, CameraModule, CameraSnapshot
from app.tbc.camera_modules import registry


class FakeCameraModule(CameraModule):
    key = "acme"
    label = "Acme"
    description = "Testmodul"
    capabilities = frozenset({CameraCapability.LIVE})

    async def probe(self, camera):
        return CameraSnapshot(status="ok", message="TP-Link geprüft")


class FakeEntryPoint:
    name = "acme"

    def load(self):
        return FakeCameraModule


class FakeEntryPoints(list):
    def select(self, *, group):
        return self if group == registry.ENTRY_POINT_GROUP else []


class CameraModuleTests(unittest.TestCase):
    def tearDown(self):
        registry.reload_camera_modules()

    def test_existing_database_is_migrated_to_reolink_module(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            with sqlite3.connect(handle.name) as connection:
                connection.executescript(
                    database.SCHEMA
                    .replace("    module_key TEXT NOT NULL DEFAULT 'reolink',\n", "")
                    .replace("    rtsp_port INTEGER NOT NULL DEFAULT 554,\n", "")
                )
            database.initialize(handle.name)
            camera_id = database.create_camera(
                handle.name,
                name="Einfahrt",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )

            camera = database.get_camera(handle.name, camera_id)

        self.assertEqual(camera["module_key"], "reolink")
        self.assertEqual(camera["rtsp_port"], 554)

    def test_registry_loads_installed_entry_point_module(self):
        registry.reload_camera_modules()
        with patch.object(registry.metadata, "entry_points", return_value=FakeEntryPoints([FakeEntryPoint()])):
            modules = registry.list_camera_modules()

        self.assertEqual(
            [module.key for module in modules],
            ["aqara", "reolink", "standard_onvif", "tplink", "acme"],
        )
        self.assertTrue(registry.get_camera_module("acme").supports(CameraCapability.LIVE))

    def test_reolink_declares_current_application_features(self):
        module = registry.get_camera_module("reolink")

        self.assertTrue(module.supports(CameraCapability.DETECTIONS))
        self.assertTrue(module.supports(CameraCapability.CHANNELS))
        self.assertTrue(module.supports(CameraCapability.ARCHIVE))

    def test_tplink_declares_only_reliably_supported_features(self):
        module = registry.get_camera_module("tplink")

        self.assertEqual(module.default_onvif_port, 2020)
        self.assertTrue(module.supports(CameraCapability.LIVE))
        self.assertTrue(module.supports(CameraCapability.DETECTIONS))
        self.assertFalse(module.supports(CameraCapability.ARCHIVE))
        self.assertFalse(module.supports(CameraCapability.RECORDING))

    def test_standard_onvif_and_aqara_modules_are_available(self):
        standard = registry.get_camera_module("standard_onvif")
        aqara = registry.get_camera_module("aqara")

        self.assertEqual(standard.default_onvif_port, 80)
        self.assertTrue(standard.supports(CameraCapability.LIVE))
        self.assertEqual(aqara.default_onvif_port, 5000)
        self.assertEqual(aqara.default_rtsp_port, 8554)
        self.assertTrue(aqara.supports(CameraCapability.CHANNELS))
        self.assertFalse(aqara.supports(CameraCapability.ARCHIVE))


if __name__ == "__main__":
    unittest.main()
