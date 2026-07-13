from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

TEST_TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 8000
_SUMMARY_LINE_PATTERN = re.compile(r"^=+ .* =+$|^\d+ \w+.*$")


@dataclass(frozen=True)
class PluginTestResult:
    ran: bool
    passed: bool
    summary: str
    output: str


async def run_plugin_tests(plugin_dir: Path) -> PluginTestResult:
    """Run a plugin's own tests/ directory with pytest, if it has one.

    Plugin code already executes with the same privileges as the TBC process
    the moment it is loaded (see docs/camera-modules.md and
    docs/cloud-accounts.md), so running its bundled tests crosses no new
    trust boundary - it is the same code, just exercised deliberately by an
    admin instead of implicitly on load.
    """
    tests_dir = plugin_dir / "tests"
    if not tests_dir.is_dir() or not any(tests_dir.glob("test_*.py")):
        return PluginTestResult(ran=False, passed=False, summary="Keine Tests im Plugin enthalten", output="")

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
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(plugin_dir),
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=TEST_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return PluginTestResult(
                ran=True,
                passed=False,
                summary=f"Tests abgebrochen: keine Rückmeldung innerhalb von {TEST_TIMEOUT_SECONDS}s",
                output="",
            )
    except OSError as exc:
        return PluginTestResult(ran=False, passed=False, summary=f"Tests konnten nicht gestartet werden: {exc}", output="")

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
