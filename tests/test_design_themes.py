import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from app.tbc.themes import registry
from app.tbc.themes.packages import (
    ThemePackageError,
    discover_theme_packages,
    export_theme_archive,
    install_theme_archive,
    read_manifest,
    remove_external_theme,
)
from app.tbc.themes.registry import get_theme_registration


def theme_archive(*, key="acme", wrapped=False, stylesheet="styles.css", extra_files=None, include_stylesheet=True):
    manifest = {
        "schema_version": 1,
        "key": key,
        "label": "Acme Design",
        "version": "1.2.3",
        "description": "Testdesign",
        "stylesheet": stylesheet,
    }
    prefix = "acme-theme/" if wrapped else ""
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(f"{prefix}manifest.json", json.dumps(manifest))
        if include_stylesheet:
            bundle.writestr(f"{prefix}static/{stylesheet}", ":root { --bg: #000; }")
        for name, value in extra_files or []:
            bundle.writestr(name, value)
    return output.getvalue()


class DesignThemePackageTests(unittest.TestCase):
    def tearDown(self):
        registry.reload_themes()

    def test_builtin_themes_are_discovered_and_exportable(self):
        with tempfile.TemporaryDirectory() as external_path:
            packages = discover_theme_packages(external_path)

        self.assertEqual(
            sorted(package.manifest.key for package in packages),
            ["midnight", "standard"],
        )
        for package in packages:
            archive = export_theme_archive(package)
            with zipfile.ZipFile(BytesIO(archive)) as bundle:
                names = set(bundle.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn(f"static/{package.manifest.stylesheet}", names)

    def test_zip_theme_can_be_installed_activated_exported_and_removed(self):
        with tempfile.TemporaryDirectory() as external_path:
            package = install_theme_archive(theme_archive(wrapped=True), external_path)
            self.assertEqual(package.manifest.key, "acme")
            self.assertEqual(package.manifest.label, "Acme Design")
            self.assertTrue((package.path / "static" / "styles.css").is_file())

            with patch.object(
                registry,
                "load_settings",
                return_value=SimpleNamespace(theme_modules_path=external_path),
            ):
                registry.reload_themes()
                registration = get_theme_registration("acme")
                self.assertEqual(registration.manifest.key, "acme")
                self.assertEqual(registration.origin, "uploaded")
            registry.reload_themes()

            exported = export_theme_archive(package)
            self.assertTrue(exported.startswith(b"PK"))
            package = install_theme_archive(exported, external_path)
            self.assertEqual(package.manifest.key, "acme")

            remove_external_theme("acme", external_path)
            self.assertFalse(package.path.exists())

    def test_zip_slip_path_is_rejected(self):
        archive = theme_archive(extra_files=[("../outside.css", "bad")])

        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(ThemePackageError, "unsicheren Dateipfad"):
                install_theme_archive(archive, external_path)

    def test_disallowed_file_type_is_rejected(self):
        archive = theme_archive(extra_files=[("evil.py", "print('no')")])

        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(ThemePackageError, "Nicht erlaubter Dateityp"):
                install_theme_archive(archive, external_path)

    def test_missing_stylesheet_is_rejected(self):
        archive = theme_archive(include_stylesheet=False)

        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(ThemePackageError, "Stylesheet"):
                install_theme_archive(archive, external_path)

    def test_builtin_theme_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(ThemePackageError, "cannot be overwritten"):
                install_theme_archive(theme_archive(key="standard"), external_path)

    def test_builtin_theme_cannot_be_removed(self):
        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(ThemePackageError, "nicht entfernt"):
                remove_external_theme("standard", external_path)

    def test_invalid_zip_is_reported_as_theme_error(self):
        with tempfile.TemporaryDirectory() as external_path:
            with self.assertRaisesRegex(ThemePackageError, "not a valid ZIP"):
                install_theme_archive(b"not a zip", external_path)

    def test_unknown_theme_key_falls_back_to_standard(self):
        registration = get_theme_registration("does-not-exist")
        self.assertEqual(registration.manifest.key, "standard")

    def test_manifest_requires_css_stylesheet(self):
        with tempfile.TemporaryDirectory() as external_path:
            manifest_path = f"{external_path}/manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema_version": 1,
                        "key": "acme",
                        "label": "Acme",
                        "version": "1.0.0",
                        "stylesheet": "../escape.css",
                    },
                    handle,
                )
            with self.assertRaisesRegex(ThemePackageError, "Invalid stylesheet"):
                read_manifest(__import__("pathlib").Path(manifest_path))


if __name__ == "__main__":
    unittest.main()
