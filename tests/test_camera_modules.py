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
        return CameraSnapshot(status="ok", message="TP-Link checked")


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

    def test_legacy_rows_migrate_to_reolink_but_new_cameras_default_to_standard_onvif(self):
        # module_key was added to the schema after TBC supported only
        # Reolink, so the migration path (database.py's MIGRATIONS tuple)
        # correctly backfills pre-existing rows to "reolink" - that's a
        # historical fact about those specific rows, not a statement that
        # Reolink is the app's preferred default going forward. A brand new
        # camera created after that migration has no such history and must
        # default to "standard_onvif", the vendor-neutral module that ships
        # built into the core app (unlike Reolink, which is an optional
        # external plugin that may not even be installed).
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            with sqlite3.connect(handle.name) as connection:
                connection.executescript(
                    database.SCHEMA
                    .replace("    module_key TEXT NOT NULL DEFAULT 'standard_onvif',\n", "")
                    .replace("    rtsp_port INTEGER NOT NULL DEFAULT 554,\n", "")
                    .replace("    manual_stream_uri TEXT,\n", "")
                    .replace("    performance_cpu REAL,\n", "")
                    .replace("    performance_codec_rate INTEGER,\n", "")
                    .replace("    performance_net_throughput INTEGER,\n", "")
                )
                connection.execute(
                    "INSERT INTO cameras (name, host, username, password) VALUES (?, ?, ?, ?)",
                    ("Legacy camera", "192.0.2.20", "admin", "secret"),
                )
            database.initialize(handle.name)
            legacy_camera_id = 1
            new_camera_id = database.create_camera(
                handle.name,
                name="Einfahrt",
                host="192.0.2.10",
                onvif_port=8000,
                http_port=80,
                username="admin",
                password="secret",
            )

            legacy_camera = database.get_camera(handle.name, legacy_camera_id)
            new_camera = database.get_camera(handle.name, new_camera_id)

        self.assertEqual(legacy_camera["module_key"], "reolink")
        self.assertEqual(legacy_camera["rtsp_port"], 554)
        self.assertIsNone(legacy_camera["manual_stream_uri"])
        self.assertIsNone(legacy_camera["performance_cpu"])

        self.assertEqual(new_camera["module_key"], "standard_onvif")

    def test_get_camera_module_defaults_to_standard_onvif_when_no_key_given(self):
        module = registry.get_camera_module(None)
        self.assertEqual(module.key, "standard_onvif")

    def test_registry_loads_installed_entry_point_module(self):
        registry.reload_camera_modules()
        with patch.object(registry.metadata, "entry_points", return_value=FakeEntryPoints([FakeEntryPoint()])):
            modules = registry.list_camera_modules()

        self.assertEqual(
            [module.key for module in modules],
            [
                "rtsp_only",
                "standard_onvif",
                "acme",
            ],
        )
        self.assertTrue(registry.get_camera_module("acme").supports(CameraCapability.LIVE))

    def test_camera_probe_persists_optional_performance_metrics(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
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

            database.update_camera_probe(
                handle.name,
                camera_id,
                status="ok",
                message="Performance gelesen",
                metrics={"cpu_used": 27, "codec_rate": 6794, "net_throughput": 42},
            )
            camera = database.get_camera(handle.name, camera_id)

        self.assertEqual(camera["performance_cpu"], 27)
        self.assertEqual(camera["performance_codec_rate"], 6794)
        self.assertEqual(camera["performance_net_throughput"], 42)

    def test_standard_onvif_module_is_available(self):
        standard = registry.get_camera_module("standard_onvif")

        self.assertEqual(standard.default_onvif_port, 80)
        self.assertTrue(standard.supports(CameraCapability.LIVE))
        self.assertTrue(standard.supports(CameraCapability.CHANNELS))

    def test_manual_rtsp_profile_is_available(self):
        module = registry.get_camera_module("rtsp_only")
        self.assertTrue(module.supports(CameraCapability.LIVE))
        self.assertTrue(module.supports_manual_stream_uri)
        self.assertTrue(module.requires_manual_stream_uri)
        self.assertFalse(module.requires_credentials)


if __name__ == "__main__":
    unittest.main()
