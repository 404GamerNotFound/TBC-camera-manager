from __future__ import annotations

import asyncio
import importlib.metadata
import os
import site
import sys
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

INSTALL_TIMEOUT_SECONDS = 180
MAX_OUTPUT_CHARS = 8000
MAX_REQUIREMENTS = 20
PLUGIN_SITE_PACKAGES_ENV = "TBC_PLUGIN_SITE_PACKAGES_PATH"


def plugin_site_packages_path() -> Path:
    """Return the persistent package directory used by external plugins.

    ``/data`` survives Home Assistant App and container-image updates, unlike
    the app user's home directory.  A custom path remains available for
    non-container deployments and tests.
    """
    configured = os.getenv(PLUGIN_SITE_PACKAGES_ENV)
    if configured:
        return Path(configured)
    database_path = Path(os.getenv("TBC_DATABASE_PATH", "/data/tbc.sqlite3"))
    return database_path.parent / "plugin-site-packages"


def activate_plugin_site_packages() -> Path:
    """Make already-persisted plugin dependencies importable in this process."""
    package_path = plugin_site_packages_path()
    if package_path.is_dir() and str(package_path) not in sys.path:
        site.addsitedir(str(package_path))
    return package_path


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


async def install_requirements(specs: tuple[str, ...]) -> str:
    """Install `specs` into the persistent plugin dependency directory.

    Admin-triggered, plugin-scoped, and time-bounded - the same trust
    boundary plugin_testing.py's run_plugin_tests() already crosses to run a
    plugin's own test suite, mirrored here (subprocess shape, timeout/kill,
    captured-output-on-failure).  The target is deliberately under `/data`
    rather than the unprivileged user's home directory: `/data` survives an
    app-image update, whereas `/home/tbc/.local` does not.
    """
    if not specs:
        return ""
    package_path = activate_plugin_site_packages()
    package_path.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--upgrade",
        "--target",
        str(package_path),
    ]
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

    # A fresh target directory is created by pip after the first install, so
    # add it only now if it did not exist when this function started.
    activate_plugin_site_packages()
    # Beyond the sys.path gap above, a missing_requirements() call later in
    # the same long-running process can still report a just-installed
    # package as missing purely from caching: Python's import system caches
    # directory listings per sys.path entry and doesn't necessarily notice a
    # new *.dist-info appearing on disk mid-process.
    importlib.invalidate_caches()
    return output[-MAX_OUTPUT_CHARS:]


# This module is imported while the plugin registries are set up.  Activating
# the directory here makes dependencies installed before a main-app update
# available again before external plugin code is loaded.
activate_plugin_site_packages()
