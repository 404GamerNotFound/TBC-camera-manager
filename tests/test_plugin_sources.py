import io
import unittest
import urllib.error
import zipfile
from unittest.mock import MagicMock, patch

from app.tbc.plugin_sources import (
    PluginSourceError,
    extract_plugin_archive,
    fetch_github_repo_archive,
    fetch_latest_commit_sha,
    parse_github_repo_url,
    resolve_and_fetch_plugin,
)


def _fake_github_zip(*, repo_root="owner-repo-abc123", entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(f"{repo_root}/", "")
        for name, content in entries.items():
            bundle.writestr(f"{repo_root}/{name}", content)
    return output.getvalue()


def _mock_response(payload: bytes):
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.read.return_value = payload
    return response


class ParseGithubRepoUrlTests(unittest.TestCase):
    def test_valid_url(self):
        repo = parse_github_repo_url("https://github.com/octocat/Hello-World")

        self.assertEqual(repo.owner, "octocat")
        self.assertEqual(repo.repo, "Hello-World")

    def test_trailing_slash_and_git_suffix_are_stripped(self):
        repo = parse_github_repo_url("https://github.com/octocat/Hello-World.git/")

        self.assertEqual(repo.repo, "Hello-World")

    def test_rejects_non_github_host(self):
        with self.assertRaisesRegex(PluginSourceError, "Ungültige"):
            parse_github_repo_url("https://gitlab.com/owner/repo")

    def test_rejects_malformed_url(self):
        with self.assertRaises(PluginSourceError):
            parse_github_repo_url("not a url")


class ExtractPluginArchiveTests(unittest.TestCase):
    def test_extracts_repo_root_when_no_subdirectory(self):
        archive = _fake_github_zip(entries={"manifest.json": "{}", "plugin.py": "x = 1"})

        result = extract_plugin_archive(archive, "")

        with zipfile.ZipFile(io.BytesIO(result)) as bundle:
            self.assertEqual(sorted(bundle.namelist()), ["plugin/manifest.json", "plugin/plugin.py"])
            self.assertEqual(bundle.read("plugin/manifest.json"), b"{}")

    def test_extracts_named_subdirectory_only(self):
        archive = _fake_github_zip(
            entries={
                "README.md": "root readme",
                "plugins/acme/manifest.json": "{}",
                "plugins/acme/plugin.py": "x = 1",
                "plugins/other/manifest.json": "{}",
            }
        )

        result = extract_plugin_archive(archive, "plugins/acme")

        with zipfile.ZipFile(io.BytesIO(result)) as bundle:
            self.assertEqual(sorted(bundle.namelist()), ["plugin/manifest.json", "plugin/plugin.py"])

    def test_missing_subdirectory_raises(self):
        archive = _fake_github_zip(entries={"manifest.json": "{}"})

        with self.assertRaisesRegex(PluginSourceError, "Kein Inhalt"):
            extract_plugin_archive(archive, "does/not/exist")

    def test_invalid_zip_raises(self):
        with self.assertRaisesRegex(PluginSourceError, "kein gültiges ZIP"):
            extract_plugin_archive(b"not a zip", "")

    def test_bundled_tests_directory_is_preserved(self):
        archive = _fake_github_zip(
            entries={
                "manifest.json": "{}",
                "plugin.py": "x = 1",
                "tests/test_plugin.py": "def test_x(): assert True",
            }
        )

        result = extract_plugin_archive(archive, "")

        with zipfile.ZipFile(io.BytesIO(result)) as bundle:
            self.assertIn("plugin/tests/test_plugin.py", bundle.namelist())


class FetchGithubRepoArchiveTests(unittest.TestCase):
    def test_404_is_reported_as_plugin_source_error(self):
        with patch("app.tbc.plugin_sources.urllib.request.urlopen") as urlopen:
            urlopen.side_effect = urllib.error.HTTPError("url", 404, "Not Found", {}, None)
            with self.assertRaisesRegex(PluginSourceError, "nicht gefunden"):
                fetch_github_repo_archive("owner", "repo", "main")

    def test_network_error_is_reported(self):
        with patch("app.tbc.plugin_sources.urllib.request.urlopen") as urlopen:
            urlopen.side_effect = urllib.error.URLError("boom")
            with self.assertRaisesRegex(PluginSourceError, "nicht erreicht"):
                fetch_github_repo_archive("owner", "repo", "main")

    def test_successful_fetch_returns_bytes(self):
        with patch("app.tbc.plugin_sources.urllib.request.urlopen", return_value=_mock_response(b"zipbytes")):
            data = fetch_github_repo_archive("owner", "repo", "main")

        self.assertEqual(data, b"zipbytes")


class FetchLatestCommitShaTests(unittest.TestCase):
    def test_returns_the_sha_from_the_response_body(self):
        with patch(
            "app.tbc.plugin_sources.urllib.request.urlopen",
            return_value=_mock_response(b"3184c5a626d4cecdc11cd90e0e3f4cd645393fa6"),
        ):
            sha = fetch_latest_commit_sha("owner", "repo", "main")

        self.assertEqual(sha, "3184c5a626d4cecdc11cd90e0e3f4cd645393fa6")

    def test_422_for_unknown_ref_is_reported_as_not_found(self):
        with patch("app.tbc.plugin_sources.urllib.request.urlopen") as urlopen:
            urlopen.side_effect = urllib.error.HTTPError("url", 422, "Unprocessable", {}, None)
            with self.assertRaisesRegex(PluginSourceError, "nicht gefunden"):
                fetch_latest_commit_sha("owner", "repo", "no-such-branch")

    def test_malformed_response_is_rejected(self):
        with patch("app.tbc.plugin_sources.urllib.request.urlopen", return_value=_mock_response(b"not a sha")):
            with self.assertRaisesRegex(PluginSourceError, "keine gültige Commit-SHA"):
                fetch_latest_commit_sha("owner", "repo", "main")


class ResolveAndFetchPluginTests(unittest.TestCase):
    def test_end_to_end_with_mocked_network(self):
        archive = _fake_github_zip(entries={"manifest.json": "{}", "plugin.py": "x=1"})
        sha = "3184c5a626d4cecdc11cd90e0e3f4cd645393fa6"
        with patch(
            "app.tbc.plugin_sources.urllib.request.urlopen",
            side_effect=[_mock_response(sha.encode()), _mock_response(archive)],
        ):
            result, resolved_sha = resolve_and_fetch_plugin("https://github.com/owner/repo", "main", "")

        self.assertEqual(resolved_sha, sha)
        with zipfile.ZipFile(io.BytesIO(result)) as bundle:
            self.assertIn("plugin/manifest.json", bundle.namelist())

    def test_invalid_repo_url_is_rejected_before_any_network_call(self):
        with patch("app.tbc.plugin_sources.urllib.request.urlopen") as urlopen:
            with self.assertRaises(PluginSourceError):
                resolve_and_fetch_plugin("https://example.com/owner/repo", "main", "")
            urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
