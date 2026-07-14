import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from app.tbc.app_updates import AppUpdateCheckError, fetch_latest_release, is_newer, parse_version


class ParseVersionTests(unittest.TestCase):
    def test_parses_plain_semver(self):
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))

    def test_parses_v_prefixed_semver(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))

    def test_rejects_malformed_strings(self):
        self.assertIsNone(parse_version("not-a-version"))
        self.assertIsNone(parse_version("1.2"))
        self.assertIsNone(parse_version(""))


class IsNewerTests(unittest.TestCase):
    def test_true_when_candidate_is_greater(self):
        self.assertTrue(is_newer("0.3.0", "0.2.0"))
        self.assertTrue(is_newer("v1.0.0", "0.9.9"))

    def test_false_when_equal_or_older(self):
        self.assertFalse(is_newer("0.2.0", "0.2.0"))
        self.assertFalse(is_newer("0.1.0", "0.2.0"))

    def test_false_when_either_side_unparseable(self):
        self.assertFalse(is_newer("garbage", "0.2.0"))
        self.assertFalse(is_newer("0.3.0", "garbage"))


class FetchLatestReleaseTests(unittest.TestCase):
    def _mock_response(self, payload: dict) -> MagicMock:
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def test_parses_tag_name_and_strips_v_prefix(self):
        with patch("urllib.request.urlopen", return_value=self._mock_response({"tag_name": "v0.3.0", "html_url": "https://example.com/release"})):
            release = fetch_latest_release()
        self.assertEqual(release.version, "0.3.0")
        self.assertEqual(release.html_url, "https://example.com/release")

    def test_raises_on_missing_or_invalid_tag(self):
        with patch("urllib.request.urlopen", return_value=self._mock_response({"tag_name": "not-a-version"})):
            with self.assertRaises(AppUpdateCheckError):
                fetch_latest_release()

    def test_raises_friendly_error_when_no_release_published_yet(self):
        error = urllib.error.HTTPError("url", 404, "Not Found", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(AppUpdateCheckError):
                fetch_latest_release()


if __name__ == "__main__":
    unittest.main()
