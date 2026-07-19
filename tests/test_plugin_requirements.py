import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.tbc.plugin_requirements import (
    MissingPluginRequirements,
    PluginRequirementsInstallError,
    install_requirements,
    missing_requirements,
    read_requirements_field,
)


class ReadRequirementsFieldTests(unittest.TestCase):
    def test_absent_field_returns_empty_tuple(self):
        self.assertEqual(read_requirements_field(None), ())

    def test_valid_list_is_returned_as_a_tuple(self):
        self.assertEqual(
            read_requirements_field(["fritzconnection==1.15.1", "aiohttp>=3.9,<4"]),
            ("fritzconnection==1.15.1", "aiohttp>=3.9,<4"),
        )

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            read_requirements_field("fritzconnection==1.15.1")

    def test_blank_entry_raises(self):
        with self.assertRaises(ValueError):
            read_requirements_field([""])

    def test_invalid_specifier_syntax_raises(self):
        with self.assertRaises(ValueError):
            read_requirements_field(["not a valid specifier!!"])

    def test_too_many_entries_raises(self):
        with self.assertRaises(ValueError):
            read_requirements_field([f"pkg{i}" for i in range(21)])


class MissingRequirementsTests(unittest.TestCase):
    def test_already_installed_package_is_satisfied(self):
        # boto3 is a real, always-installed dependency of this app itself -
        # exercising the real importlib.metadata lookup, not a mock.
        self.assertEqual(missing_requirements(("boto3",)), ())

    def test_installed_package_with_satisfied_version_range_is_satisfied(self):
        import importlib.metadata

        installed = importlib.metadata.version("boto3")
        self.assertEqual(missing_requirements((f"boto3>={installed}",)), ())

    def test_installed_package_with_unsatisfied_version_is_missing(self):
        self.assertEqual(missing_requirements(("boto3==0.0.0.dev0",)), ("boto3==0.0.0.dev0",))

    def test_never_installed_package_is_missing(self):
        self.assertEqual(
            missing_requirements(("definitely-not-a-real-package-xyz==1.0",)),
            ("definitely-not-a-real-package-xyz==1.0",),
        )

    def test_only_the_unsatisfied_entries_are_returned(self):
        result = missing_requirements(("boto3", "definitely-not-a-real-package-xyz"))
        self.assertEqual(result, ("definitely-not-a-real-package-xyz",))

    def test_empty_requirements_is_always_satisfied(self):
        self.assertEqual(missing_requirements(()), ())


class MissingPluginRequirementsExceptionTests(unittest.TestCase):
    def test_carries_missing_specs_and_label(self):
        exc = MissingPluginRequirements(("fritzconnection==1.15.1",), plugin_label="AVM FRITZ!Box")

        self.assertEqual(exc.missing, ("fritzconnection==1.15.1",))
        self.assertEqual(exc.plugin_label, "AVM FRITZ!Box")
        self.assertIn("fritzconnection==1.15.1", str(exc))

    def test_carries_plugin_kind_and_module_key(self):
        # Lets the install route know which already-configured cameras (etc.)
        # to auto-refresh once the packages are actually installed - see
        # install_plugin_requirements_route in main.py.
        exc = MissingPluginRequirements(
            ("reolink-aio==0.21.3",), plugin_label="Reolink", plugin_kind="camera", module_key="reolink"
        )

        self.assertEqual(exc.plugin_kind, "camera")
        self.assertEqual(exc.module_key, "reolink")

    def test_plugin_kind_and_module_key_default_to_empty_string(self):
        exc = MissingPluginRequirements(("pkg==1.0",))

        self.assertEqual(exc.plugin_kind, "")
        self.assertEqual(exc.module_key, "")


class InstallRequirementsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.package_directory = tempfile.TemporaryDirectory()
        self.package_path = Path(self.package_directory.name) / "plugin-site-packages"
        self.plugin_path_patch = patch(
            "app.tbc.plugin_requirements.plugin_site_packages_path", return_value=self.package_path
        )
        self.plugin_path_patch.start()
        self.addCleanup(self.plugin_path_patch.stop)
        self.addCleanup(self.package_directory.cleanup)

    async def test_empty_specs_is_a_no_op(self):
        with patch("app.tbc.plugin_requirements.asyncio.create_subprocess_exec") as create_subprocess:
            result = await install_requirements(())

        self.assertEqual(result, "")
        create_subprocess.assert_not_called()

    async def test_successful_install_returns_captured_output(self):
        process = AsyncMock()
        process.communicate = AsyncMock(return_value=(b"Successfully installed fritzconnection-1.15.1\n", None))
        process.returncode = 0

        with patch("app.tbc.plugin_requirements.asyncio.create_subprocess_exec", return_value=process) as create_subprocess:
            output = await install_requirements(("fritzconnection==1.15.1",))

        self.assertIn("Successfully installed", output)
        args = create_subprocess.call_args.args
        self.assertIn("pip", args)
        self.assertIn("install", args)
        self.assertIn("fritzconnection==1.15.1", args)

    async def test_successful_install_invalidates_import_caches(self):
        # Regression test: without this, missing_requirements() called again
        # later in the same long-running process could still report a
        # just-installed package as missing, because Python's import system
        # caches directory listings and doesn't necessarily notice a new
        # *.dist-info appearing on disk mid-process - this was reported as
        # the confirm/install flow looping forever against a real deployment.
        process = AsyncMock()
        process.communicate = AsyncMock(return_value=(b"Successfully installed fritzconnection-1.15.1\n", None))
        process.returncode = 0

        with (
            patch("app.tbc.plugin_requirements.asyncio.create_subprocess_exec", return_value=process),
            patch("app.tbc.plugin_requirements.importlib.invalidate_caches") as invalidate_caches,
        ):
            await install_requirements(("fritzconnection==1.15.1",))

        invalidate_caches.assert_called_once()

    async def test_nonzero_exit_raises_with_output(self):
        process = AsyncMock()
        process.communicate = AsyncMock(return_value=(b"ERROR: Could not find a version\n", None))
        process.returncode = 1

        with patch("app.tbc.plugin_requirements.asyncio.create_subprocess_exec", return_value=process):
            with self.assertRaisesRegex(PluginRequirementsInstallError, "Could not find a version"):
                await install_requirements(("nonexistent-package==9.9.9",))

    async def test_timeout_kills_the_process_and_raises(self):
        process = AsyncMock()
        process.communicate = AsyncMock(return_value=(b"", None))
        process.kill = MagicMock()
        process.wait = AsyncMock()

        async def _fake_wait_for(coro, timeout):
            coro.close()  # avoid a "coroutine was never awaited" warning
            raise asyncio.TimeoutError()

        with patch("app.tbc.plugin_requirements.asyncio.create_subprocess_exec", return_value=process):
            with patch("app.tbc.plugin_requirements.asyncio.wait_for", new=_fake_wait_for):
                with self.assertRaisesRegex(PluginRequirementsInstallError, "timed out"):
                    await install_requirements(("fritzconnection==1.15.1",))

        process.kill.assert_called_once()

    async def test_exec_failure_raises(self):
        with patch("app.tbc.plugin_requirements.asyncio.create_subprocess_exec", side_effect=OSError("pip not found")):
            with self.assertRaisesRegex(PluginRequirementsInstallError, "pip not found"):
                await install_requirements(("fritzconnection==1.15.1",))

    async def test_install_targets_the_persistent_plugin_directory(self):
        process = AsyncMock()
        process.communicate = AsyncMock(return_value=(b"", None))
        process.returncode = 0

        with tempfile.TemporaryDirectory() as directory:
            package_path = Path(directory) / "plugin-site-packages"
            with (
                patch("app.tbc.plugin_requirements.plugin_site_packages_path", return_value=package_path),
                patch("app.tbc.plugin_requirements.asyncio.create_subprocess_exec", return_value=process) as create_subprocess,
                patch("app.tbc.plugin_requirements.site.addsitedir") as addsitedir,
            ):
                await install_requirements(("fritzconnection==1.15.1",))

        args = create_subprocess.call_args.args
        self.assertEqual(args[args.index("--target") + 1], str(package_path))
        self.assertIn("--upgrade", args)
        self.assertNotIn("--user", args)
        addsitedir.assert_called_once_with(str(package_path))


if __name__ == "__main__":
    unittest.main()
