from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from io import BytesIO

GITHUB_REPO_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/"
    r"(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 30


class PluginSourceError(ValueError):
    pass


@dataclass(frozen=True)
class GithubRepo:
    owner: str
    repo: str


def parse_github_repo_url(url: str) -> GithubRepo:
    match = GITHUB_REPO_PATTERN.match(url.strip())
    if not match:
        raise PluginSourceError(
            "Ungültige GitHub-Repository-URL. Erwartet wird https://github.com/<besitzer>/<repository> "
            "(nur öffentliche GitHub-Repositories werden unterstützt)."
        )
    return GithubRepo(owner=match.group("owner"), repo=match.group("repo"))


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
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise PluginSourceError(
                f"Repository oder Branch/Tag nicht gefunden (ist '{owner}/{repo}' öffentlich, existiert '{ref}'?)"
            ) from exc
        raise PluginSourceError(f"GitHub-Anfrage fehlgeschlagen: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise PluginSourceError(f"GitHub konnte nicht erreicht werden: {exc.reason}") from exc
    if len(data) > MAX_ARCHIVE_BYTES:
        raise PluginSourceError("Repository-Archiv ist größer als 25 MB")
    return data


def extract_plugin_archive(archive: bytes, subdirectory: str) -> bytes:
    """Re-wrap a downloaded GitHub repo archive's subdirectory into a plugin-shaped ZIP.

    GitHub always wraps a repo archive in a single `<owner>-<repo>-<sha>/`
    folder; this strips that (and, if given, descends into `subdirectory`)
    and re-zips the contents under one synthetic top-level folder - the same
    "one shared top folder" shape every install_*_archive() already
    validates, so a GitHub-sourced install goes through the exact same
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
                rewritten.writestr(f"plugin/{relative}", bundle.read(name))
        return output.getvalue()


def fetch_and_repackage_plugin(url: str, ref: str, subdirectory: str) -> bytes:
    """Fetch a public GitHub repo and repackage it as an installable plugin ZIP.

    Synchronous and network-bound; callers on the request path must run this
    via asyncio.to_thread() to avoid blocking the event loop.
    """
    github_repo = parse_github_repo_url(url)
    archive = fetch_github_repo_archive(github_repo.owner, github_repo.repo, ref)
    return extract_plugin_archive(archive, subdirectory)
