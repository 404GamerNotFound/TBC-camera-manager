from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

GITHUB_REPO_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/"
    r"(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)
SHA_PATTERN = re.compile(r"[0-9a-f]{7,40}")
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 30
IGNORED_REPOSITORY_FILES = frozenset(
    {".DS_Store", ".dockerignore", ".editorconfig", ".gitattributes", ".gitignore", ".gitmodules"}
)
IGNORED_REPOSITORY_DIRECTORIES = frozenset(
    {".git", ".github", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
)
IGNORED_REPOSITORY_SUFFIXES = frozenset({".pyc", ".pyo"})


class PluginSourceError(ValueError):
    pass


@dataclass(frozen=True)
class GithubRepo:
    owner: str
    repo: str


@dataclass(frozen=True)
class StandardPluginSource:
    key: str
    plugin_kind: str
    label: str
    description: str
    repo_url: str
    ref: str = "main"
    subdirectory: str = ""


@dataclass(frozen=True)
class PluginInstallCandidate:
    key: str
    plugin_kind: str
    label: str
    description: str
    install_url: str


STANDARD_PLUGIN_SOURCES = (
    StandardPluginSource(
        key="aqara",
        plugin_kind="camera",
        label="Aqara",
        description="Aqara-Kameras sowie kompatible Video-Türklingeln",
        repo_url="https://github.com/404GamerNotFound/TBC-aqara",
    ),
    StandardPluginSource(
        key="axis",
        plugin_kind="camera",
        label="Axis",
        description="Axis-Netzwerkkameras über ONVIF Profile S/T",
        repo_url="https://github.com/404GamerNotFound/TBC-axis",
    ),
    StandardPluginSource(
        key="dahua",
        plugin_kind="camera",
        label="Dahua",
        description="Dahua-Kameras und NVR (inkl. Amcrest/Annke-OEMs) über ONVIF und RTSP",
        repo_url="https://github.com/404GamerNotFound/TBC-dahua",
    ),
    StandardPluginSource(
        key="foscam",
        plugin_kind="camera",
        label="Foscam",
        description="Foscam-Kameras über ONVIF und RTSP",
        repo_url="https://github.com/404GamerNotFound/TBC-foscam",
    ),
    StandardPluginSource(
        key="hikvision",
        plugin_kind="camera",
        label="Hikvision",
        description="Hikvision-Kameras und NVR über ONVIF und RTSP",
        repo_url="https://github.com/404GamerNotFound/TBC-hikvision",
    ),
    StandardPluginSource(
        key="reolink",
        plugin_kind="camera",
        label="Reolink",
        description="Reolink-Kameras und NVR via ONVIF und reolink-aio",
        repo_url="https://github.com/404GamerNotFound/TBC-reolink",
    ),
    StandardPluginSource(
        key="sonoff",
        plugin_kind="camera",
        label="SONOFF",
        description="SONOFF-Kameras über den in eWeLink erzeugten RTSP-Link",
        repo_url="https://github.com/404GamerNotFound/TBC-sonoff",
    ),
    StandardPluginSource(
        key="tplink",
        plugin_kind="camera",
        label="TP-Link / Tapo",
        description="TP-Link-Tapo-Kameras via ONVIF und RTSP",
        repo_url="https://github.com/404GamerNotFound/TBC-tplink",
    ),
    StandardPluginSource(
        key="ubiquiti",
        plugin_kind="camera",
        label="Ubiquiti / UniFi Protect",
        description="UniFi-Protect-Kameras über einen erzeugten RTSP-/RTSPS-Link",
        repo_url="https://github.com/404GamerNotFound/TBC-ubiquiti",
    ),
)


def get_standard_plugin_source(key: str) -> StandardPluginSource | None:
    normalized_key = key.strip().lower()
    return next((source for source in STANDARD_PLUGIN_SOURCES if source.key == normalized_key), None)


def list_uninstalled_plugin_candidates(
    plugin_kind: str,
    installed_keys: Iterable[str],
    registered_sources: Iterable[Mapping[str, object]],
) -> tuple[PluginInstallCandidate, ...]:
    """Return known plugin modules that are available but not currently installed.

    Standard repositories have a stable module key before their first installation.
    Arbitrary registered repositories become selectable only after at least one successful
    synchronization recorded their ``installed_key``; before that, their manifest identity is
    unknown and they are merely sources rather than known modules.
    """

    normalized_kind = plugin_kind.strip().lower()
    installed = {str(key).strip().lower() for key in installed_keys if str(key).strip()}
    candidates: dict[str, PluginInstallCandidate] = {}

    for source in STANDARD_PLUGIN_SOURCES:
        if source.plugin_kind != normalized_kind or source.key in installed:
            continue
        candidates[source.key] = PluginInstallCandidate(
            key=source.key,
            plugin_kind=source.plugin_kind,
            label=source.label,
            description=source.description,
            install_url=f"/plugin-sources#standard-source-{source.key}",
        )

    for source in registered_sources:
        if str(source.get("plugin_kind") or "").strip().lower() != normalized_kind:
            continue
        key = str(source.get("installed_key") or "").strip().lower()
        if not key or key in installed or key in candidates:
            continue
        source_id = source.get("id")
        install_url = f"/plugin-sources#source-{source_id}" if source_id is not None else "/plugin-sources"
        candidates[key] = PluginInstallCandidate(
            key=key,
            plugin_kind=normalized_kind,
            label=str(source.get("label") or key).strip() or key,
            description="",
            install_url=install_url,
        )

    return tuple(candidates.values())


def parse_github_repo_url(url: str) -> GithubRepo:
    match = GITHUB_REPO_PATTERN.match(url.strip())
    if not match:
        raise PluginSourceError(
            "Ungültige GitHub-Repository-URL. Erwartet wird https://github.com/<besitzer>/<repository> "
            "(nur öffentliche GitHub-Repositories werden unterstützt)."
        )
    return GithubRepo(owner=match.group("owner"), repo=match.group("repo"))


def github_repositories_match(first_url: str, second_url: str) -> bool:
    first = parse_github_repo_url(first_url)
    second = parse_github_repo_url(second_url)
    return (first.owner.casefold(), first.repo.casefold()) == (
        second.owner.casefold(),
        second.repo.casefold(),
    )


def fetch_github_repo_archive(owner: str, repo: str, ref: str) -> bytes:
    """Download a public GitHub repository as a ZIP via the official archive API.

    Uses only the unauthenticated `zipball` endpoint of the GitHub REST API,
    which works for any public repository without a token; a private
    repository (or a wrong owner/repo/ref) fails with a 404, surfaced here as
    PluginSourceError instead of a generic network error.
    """
    ref = ref.strip() or "main"
    url = f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/zipball/{urllib.parse.quote(ref)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TBC-camera-manager", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_ARCHIVE_BYTES + 1)
    except urllib.error.URLError as exc:
        raise _translate_urllib_error(exc, owner, repo, ref) from exc
    if len(data) > MAX_ARCHIVE_BYTES:
        raise PluginSourceError("Repository-Archiv ist größer als 25 MB")
    return data


def fetch_latest_commit_sha(owner: str, repo: str, ref: str) -> str:
    """Look up the current commit SHA a branch/tag points to, without downloading the archive.

    Used for periodic update checks: comparing this to the SHA recorded at
    install time is far cheaper than re-downloading and re-diffing the whole
    repository archive every 60 minutes.
    """
    ref = ref.strip() or "main"
    url = f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/commits/{urllib.parse.quote(ref)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TBC-camera-manager", "Accept": "application/vnd.github.sha"},
    )
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            data = response.read(200)
    except urllib.error.URLError as exc:
        raise _translate_urllib_error(exc, owner, repo, ref) from exc
    sha = data.decode("ascii", errors="replace").strip()
    if not SHA_PATTERN.fullmatch(sha):
        raise PluginSourceError("GitHub hat keine gültige Commit-SHA geliefert")
    return sha


def _translate_urllib_error(exc: urllib.error.URLError, owner: str, repo: str, ref: str) -> PluginSourceError:
    if isinstance(exc, urllib.error.HTTPError):
        # The zipball endpoint answers an unknown repo/ref with 404; the
        # commits endpoint (used for update checks) answers an unknown ref
        # with 422 instead - both mean the same thing to an admin here.
        if exc.code in (404, 422):
            return PluginSourceError(
                f"Repository oder Branch/Tag nicht gefunden (ist '{owner}/{repo}' öffentlich, existiert '{ref}'?)"
            )
        return PluginSourceError(f"GitHub-Anfrage fehlgeschlagen: HTTP {exc.code}")
    return PluginSourceError(f"GitHub konnte nicht erreicht werden: {exc.reason}")


def extract_plugin_archive(archive: bytes, subdirectory: str) -> bytes:
    """Re-wrap a downloaded GitHub repo archive's subdirectory into a plugin-shaped ZIP.

    GitHub always wraps a repo archive in a single `<owner>-<repo>-<sha>/`
    folder; this strips that (and, if given, descends into `subdirectory`)
    and re-zips the contents under one synthetic top-level folder - the same
    "one shared top folder" shape every install_*_archive() already
    validates. Repository-only metadata such as `.gitattributes` and
    `.github/`, as well as generated caches such as `__pycache__/`, is
    intentionally omitted because it is not part of the runtime plugin
    package. A GitHub-sourced install still goes through the exact same
    security checks (path traversal, allowed file types, size limits) as a
    manually uploaded ZIP. Nothing here is a substitute for that validation.
    """
    try:
        bundle = zipfile.ZipFile(BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise PluginSourceError("Von GitHub geladene Datei ist kein gültiges ZIP-Archiv") from exc
    subdirectory = subdirectory.strip().strip("/")
    with bundle:
        names = bundle.namelist()
        if not names:
            raise PluginSourceError("Repository-Archiv ist leer")
        repo_root = names[0].split("/", 1)[0]
        prefix = f"{repo_root}/{subdirectory}/" if subdirectory else f"{repo_root}/"
        members = [name for name in names if name.startswith(prefix) and name != prefix]
        if not members:
            message = (
                f"Kein Inhalt unter '{subdirectory}' im Repository gefunden"
                if subdirectory
                else "Repository-Archiv ist leer"
            )
            raise PluginSourceError(message)
        output = BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as rewritten:
            for name in members:
                if name.endswith("/"):
                    continue
                relative = name[len(prefix):]
                if not relative:
                    continue
                relative_path = PurePosixPath(relative)
                if (
                    relative_path.name in IGNORED_REPOSITORY_FILES
                    or relative_path.suffix.lower() in IGNORED_REPOSITORY_SUFFIXES
                    or any(part in IGNORED_REPOSITORY_DIRECTORIES for part in relative_path.parts)
                ):
                    continue
                rewritten.writestr(f"plugin/{relative}", bundle.read(name))
        return output.getvalue()


def resolve_and_fetch_plugin(url: str, ref: str, subdirectory: str) -> tuple[bytes, str]:
    """Fetch a public GitHub repo and repackage it as an installable plugin ZIP.

    Resolves `ref` (a branch or tag name) to a concrete commit SHA first and
    fetches the archive at that exact SHA, so the returned SHA is precisely
    what was packaged - not just "whatever the branch pointed to a moment
    earlier" if it moved between two separate requests. Callers use the
    returned SHA to record what was actually installed (see
    database.update_plugin_source_sync_result) and to detect updates later.

    Synchronous and network-bound; callers on the request path must run this
    via asyncio.to_thread() to avoid blocking the event loop.
    """
    github_repo = parse_github_repo_url(url)
    sha = fetch_latest_commit_sha(github_repo.owner, github_repo.repo, ref)
    archive = fetch_github_repo_archive(github_repo.owner, github_repo.repo, sha)
    return extract_plugin_archive(archive, subdirectory), sha
