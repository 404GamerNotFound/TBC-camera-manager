from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

TEST_TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 8000
_SUMMARY_LINE_PATTERN = re.compile(r"^=+ .* =+$|^\d+ \w+.*$")
# app/tbc/plugin_testing.py -> app/tbc -> app -> repo root. Passed to the test
# subprocess explicitly (see run_plugin_tests) rather than relying on
# pytest's own rootdir/pythonpath discovery, which only finds this
# repository's pytest.ini when the plugin happens to live inside it -
# externally installed plugins (e.g. under /data/camera-modules/<key>/) do
# not, and still need `import app.tbc...` to work for the bootstrap below.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BOOTSTRAP_MODULE = {
    "camera": "app.tbc.camera_modules.pytest_bootstrap",
    "cloud": "app.tbc.cloud_modules.pytest_bootstrap",
    "network": "app.tbc.network_modules.pytest_bootstrap",
}


@dataclass(frozen=True)
class PluginTestResult:
    ran: bool
    passed: bool
    summary: str
    output: str


async def run_plugin_tests(plugin_dir: Path, plugin_kind: str) -> PluginTestResult:
    """Run a plugin's own tests/ directory with pytest, if it has one.

    Plugin code already executes with the same privileges as the TBC process
    the moment it is loaded (see docs/camera-modules.md and
    docs/cloud-accounts.md), so running its bundled tests crosses no new
    trust boundary - it is the same code, just exercised deliberately by an
    admin instead of implicitly on load.

    `plugin_kind` ("camera", "cloud", or "network") selects which
    `tbc_camera_api`/`tbc_cloud_api`/`tbc_network_api` facade bootstrap to
    preload, so a plugin's tests can import the same facade its own
    module.py uses - the test subprocess otherwise starts with a clean
    sys.modules and never sees it.
    """
    tests_dir = plugin_dir / "tests"
    if not tests_dir.is_dir() or not any(tests_dir.glob("test_*.py")):
        return PluginTestResult(ran=False, passed=False, summary="The plugin contains no tests", output="")

    bootstrap_args = []
    bootstrap_module = _BOOTSTRAP_MODULE.get(plugin_kind)
    if bootstrap_module:
        bootstrap_args = ["-p", bootstrap_module]

    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pytest",
            str(tests_dir),
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            *bootstrap_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(plugin_dir),
            env=env,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=TEST_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return PluginTestResult(
                ran=True,
                passed=False,
                summary=f"Tests aborted: no response within {TEST_TIMEOUT_SECONDS}s",
                output="",
            )
    except OSError as exc:
        return PluginTestResult(ran=False, passed=False, summary=f"Tests could not be started: {exc}", output="")

    output = stdout.decode("utf-8", errors="replace")
    return PluginTestResult(
        ran=True,
        passed=process.returncode == 0,
        summary=_extract_summary(output, process.returncode),
        output=output[-MAX_OUTPUT_CHARS:],
    )


def _extract_summary(output: str, returncode: int) -> str:
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    for line in reversed(lines):
        if _SUMMARY_LINE_PATTERN.match(line) and not line.startswith("="):
            return line
    return "Tests abgeschlossen" if returncode == 0 else f"Tests fehlgeschlagen (Exit-Code {returncode})"
