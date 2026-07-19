import asyncio
import unittest
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


class InstallRequirementsTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_user_flag_is_omitted_inside_a_virtualenv(self):
        process = AsyncMock()
        process.communicate = AsyncMock(return_value=(b"", None))
        process.returncode = 0

        with patch("app.tbc.plugin_requirements._in_virtualenv", return_value=True):
            with patch(
                "app.tbc.plugin_requirements.asyncio.create_subprocess_exec", return_value=process
            ) as create_subprocess:
                await install_requirements(("fritzconnection==1.15.1",))

        self.assertNotIn("--user", create_subprocess.call_args.args)

    async def test_user_flag_is_included_outside_a_virtualenv(self):
        process = AsyncMock()
        process.communicate = AsyncMock(return_value=(b"", None))
        process.returncode = 0

        with patch("app.tbc.plugin_requirements._in_virtualenv", return_value=False):
            with patch(
                "app.tbc.plugin_requirements.asyncio.create_subprocess_exec", return_value=process
            ) as create_subprocess:
                await install_requirements(("fritzconnection==1.15.1",))

        self.assertIn("--user", create_subprocess.call_args.args)


if __name__ == "__main__":
    unittest.main()
