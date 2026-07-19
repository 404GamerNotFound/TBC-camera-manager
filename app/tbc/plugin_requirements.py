from __future__ import annotations

import asyncio
import importlib.metadata
import site
import sys
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

INSTALL_TIMEOUT_SECONDS = 180
MAX_OUTPUT_CHARS = 8000
MAX_REQUIREMENTS = 20


class MissingPluginRequirements(Exception):
    """Raised when a plugin's declared pip requirements aren't satisfied yet.

    Carries the exact unsatisfied specifier strings (and the plugin's label,
    for a clear message) so the caller can show an admin a confirmation step
    before anything gets installed - see plugin_requirements_confirm.html.
    `plugin_kind`/`module_key` identify which installed module this install
    would have become, so that once the packages are actually installed,
    already-configured cameras/accounts using that same module can be
    refreshed automatically instead of showing stale probe results until the
    next background poll or a manual refresh.
    """

    def __init__(
        self,
        missing: tuple[str, ...],
        *,
        plugin_label: str = "",
        plugin_kind: str = "",
        module_key: str = "",
    ) -> None:
        super().__init__(f"Missing Python packages: {', '.join(missing)}")
        self.missing = missing
        self.plugin_label = plugin_label
        self.plugin_kind = plugin_kind
        self.module_key = module_key


class PluginRequirementsInstallError(RuntimeError):
    """Raised when `pip install` for a plugin's requirements fails or times out."""


def read_requirements_field(raw: Any) -> tuple[str, ...]:
    """Parse a manifest's optional "requirements" list of pip specifier strings.

    Absent entirely (the common case - most plugins need nothing beyond
    what TBC itself already ships) yields an empty tuple, not an error.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_REQUIREMENTS:
        raise ValueError(f"requirements must be a list with at most {MAX_REQUIREMENTS} entries")
    specs: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError("Each requirements entry must be a non-empty string")
        spec = entry.strip()
        try:
            Requirement(spec)
        except InvalidRequirement as exc:
            raise ValueError(f"Invalid requirement specifier: {spec}") from exc
        specs.append(spec)
    return tuple(specs)


def missing_requirements(requirements: tuple[str, ...]) -> tuple[str, ...]:
    """Return the subset of `requirements` not already satisfied in this environment.

    Checked by distribution name (the pip/PyPI package name, e.g.
    "fritzconnection") via importlib.metadata, not by import name - manifest
    requirements are pip specifier strings, and the two don't always match.
    """
    missing: list[str] = []
    for spec in requirements:
        requirement = Requirement(spec)
        try:
            installed_version = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(spec)
            continue
        if not requirement.specifier.contains(installed_version, prereleases=True):
            missing.append(spec)
    return tuple(missing)


def _in_virtualenv() -> bool:
    return sys.prefix != sys.base_prefix


async def install_requirements(specs: tuple[str, ...]) -> str:
    """Install `specs` via pip into the running Python environment.

    Admin-triggered, plugin-scoped, and time-bounded - the same trust
    boundary plugin_testing.py's run_plugin_tests() already crosses to run a
    plugin's own test suite, mirrored here (subprocess shape, timeout/kill,
    captured-output-on-failure). Uses `--user` unless already running inside
    a virtualenv (pip rejects --user there) - the container drops to an
    unprivileged user before startup (see container_launcher.py) that can't
    write to the system site-packages otherwise.
    """
    if not specs:
        return ""
    used_user_flag = not _in_virtualenv()
    command = [sys.executable, "-m", "pip", "install", "--no-cache-dir"]
    if used_user_flag:
        command.append("--user")
    command.extend(specs)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=INSTALL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise PluginRequirementsInstallError(
                f"pip install timed out after {INSTALL_TIMEOUT_SECONDS}s"
            ) from exc
    except OSError as exc:
        raise PluginRequirementsInstallError(f"pip could not be started: {exc}") from exc

    output = stdout.decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise PluginRequirementsInstallError(output[-MAX_OUTPUT_CHARS:] or f"pip exited with code {process.returncode}")

    if used_user_flag:
        # On a fresh container, the --user site-packages directory
        # (~/.local/lib/pythonX.Y/site-packages) does not exist yet at
        # interpreter startup, so Python's own site.py never added it to
        # sys.path in the first place (it only does so if the directory
        # already exists - see CPython's site.addusersitepackages()).
        # pip creates it now, on the first-ever --user install, but nothing
        # else in this process would ever look there without this: not even
        # importlib.invalidate_caches() below, since that only refreshes
        # finders for paths *already on* sys.path.
        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            site.addsitedir(user_site)
    # Beyond the sys.path gap above, a missing_requirements() call later in
    # the same long-running process can still report a just-installed
    # package as missing purely from caching: Python's import system caches
    # directory listings per sys.path entry and doesn't necessarily notice a
    # new *.dist-info appearing on disk mid-process.
    importlib.invalidate_caches()
    return output[-MAX_OUTPUT_CHARS:]
