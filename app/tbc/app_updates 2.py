from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__

GITHUB_OWNER = "404GamerNotFound"
GITHUB_REPO = "TBC-camera-manager"
FETCH_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 200_000
_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class AppUpdateCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class LatestRelease:
    version: str
    html_url: str


def current_version() -> str:
    return __version__


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_PATTERN.match(value.strip())
    if not match:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return (major, minor, patch)


def is_newer(candidate: str, current: str) -> bool:
    candidate_parts = parse_version(candidate)
    current_parts = parse_version(current)
    if candidate_parts is None or current_parts is None:
        return False
    return candidate_parts > current_parts


def fetch_latest_release() -> LatestRelease:
    """Looks up the latest published GitHub Release of the TBC application itself.

    Distinct from plugin_sources.fetch_latest_commit_sha, which tracks arbitrary
    branch/tag commits for installable plugins - the app itself is only considered
    "updatable" when a new tagged Release (vX.Y.Z) is published, since applying an
    update means pulling a new image/commit by hand, not a one-click install.
    """
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TBC-camera-manager", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise AppUpdateCheckError("No GitHub release has been published yet") from exc
        raise AppUpdateCheckError(f"GitHub-Release konnte nicht abgerufen werden: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise AppUpdateCheckError(f"GitHub-Release konnte nicht abgerufen werden: {exc.reason}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise AppUpdateCheckError("GitHub did not return a valid response") from exc
    tag_name = str(data.get("tag_name") or "").strip()
    if parse_version(tag_name) is None:
        raise AppUpdateCheckError(f"GitHub release does not have a valid version tag: {tag_name!r}")
    return LatestRelease(version=tag_name.lstrip("vV"), html_url=str(data.get("html_url") or ""))
