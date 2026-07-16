import io
import unittest
import urllib.error
import zipfile
from unittest.mock import MagicMock, patch

from app.tbc.plugin_sources import (
    STANDARD_PLUGIN_SOURCES,
    PluginSourceError,
    extract_plugin_archive,
    fetch_github_repo_archive,
    fetch_latest_commit_sha,
    get_standard_plugin_source,
    github_repositories_match,
    list_uninstalled_plugin_candidates,
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
        with self.assertRaisesRegex(PluginSourceError, "Invalid GitHub repository"):
            parse_github_repo_url("https://gitlab.com/owner/repo")

    def test_rejects_malformed_url(self):
        with self.assertRaises(PluginSourceError):
            parse_github_repo_url("not a url")

    def test_repository_comparison_normalizes_case_suffix_and_slash(self):
        self.assertTrue(
            github_repositories_match(
                "https://github.com/404gamernotfound/tbc-AQARA.git/",
                "https://github.com/404GamerNotFound/TBC-aqara",
            )
        )


class StandardPluginSourceTests(unittest.TestCase):
    def test_camera_standard_repositories_are_available(self):
        expected_repositories = {
            "aqara": "TBC-aqara",
            "axis": "TBC-axis",
            "dahua": "TBC-dahua",
            "foscam": "TBC-foscam",
            "hikvision": "TBC-hikvision",
            "reolink": "TBC-reolink",
            "sonoff": "TBC-sonoff",
            "tplink": "TBC-tplink",
            "ubiquiti": "TBC-ubiquiti",
        }

        self.assertEqual({source.key for source in STANDARD_PLUGIN_SOURCES}, set(expected_repositories))
        for key, repository in expected_repositories.items():
            with self.subTest(key=key):
                source = get_standard_plugin_source(key.upper())
                self.assertIsNotNone(source)
                self.assertEqual(source.plugin_kind, "camera")
                self.assertEqual(source.repo_url, f"https://github.com/404GamerNotFound/{repository}")
                self.assertEqual(source.ref, "main")
                self.assertEqual(source.subdirectory, "")
                self.assertIn(source, STANDARD_PLUGIN_SOURCES)

    def test_unknown_standard_repository_returns_none(self):
        self.assertIsNone(get_standard_plugin_source("unknown"))

    def test_uninstalled_camera_candidates_include_standard_and_known_registered_modules(self):
        candidates = list_uninstalled_plugin_candidates(
            "camera",
            installed_keys={"reolink", "axis"},
            registered_sources=(
                {
                    "id": 17,
                    "plugin_kind": "camera",
                    "label": "Acme Cameras",
                    "installed_key": "acme",
                },
                {
                    "id": 18,
                    "plugin_kind": "camera",
                    "label": "Not synchronized",
                    "installed_key": None,
                },
            ),
        )

        by_key = {candidate.key: candidate for candidate in candidates}
        self.assertNotIn("reolink", by_key)
        self.assertNotIn("axis", by_key)
        self.assertIn("aqara", by_key)
        self.assertEqual(by_key["aqara"].install_url, "/plugin-sources#standard-source-aqara")
        self.assertEqual(by_key["acme"].label, "Acme Cameras")
        self.assertEqual(by_key["acme"].install_url, "/plugin-sources#source-17")
        self.assertNotIn("not synchronized", {candidate.label.lower() for candidate in candidates})

    def test_cloud_candidates_only_include_known_cloud_sources(self):
        candidates = list_uninstalled_plugin_candidates(
            "cloud",
            installed_keys=(),
            registered_sources=(
                {
                    "id": 21,
                    "plugin_kind": "cloud",
                    "label": "Example Cloud",
                    "installed_key": "example-cloud",
                },
                {
                    "id": 22,
                    "plugin_kind": "camera",
                    "label": "Example Camera",
                    "installed_key": "example-camera",
                },
            ),
        )

        self.assertEqual([candidate.key for candidate in candidates], ["example-cloud"])
        self.assertEqual(candidates[0].install_url, "/plugin-sources#source-21")

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
        with self.assertRaisesRegex(PluginSourceError, "not a valid ZIP"):
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

    def test_repository_metadata_is_not_added_to_the_plugin_package(self):
        archive = _fake_github_zip(
            entries={
                ".gitattributes": "* text=auto",
                ".gitignore": "__pycache__/",
                ".github/workflows/tests.yml": "name: tests",
                "__pycache__/plugin.cpython-311.pyc": b"compiled",
                "module.pyc": b"compiled",
                "manifest.json": "{}",
                "plugin.py": "x = 1",
            }
        )

        result = extract_plugin_archive(archive, "")

        with zipfile.ZipFile(io.BytesIO(result)) as bundle:
            self.assertEqual(sorted(bundle.namelist()), ["plugin/manifest.json", "plugin/plugin.py"])


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
            with self.assertRaisesRegex(PluginSourceError, "valid commit SHA"):
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
