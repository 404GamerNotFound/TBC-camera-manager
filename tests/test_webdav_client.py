import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from app.tbc import webdav_client

TARGET = {
    "webdav_url": "https://cloud.example.invalid/remote.php/dav/files/user/tbc-recordings",
    "webdav_username": "tbc",
    "webdav_password": "s3cret",
}

_PROPFIND_BODY = b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/user/tbc-recordings/tbc-backups/</d:href>
    <d:propstat><d:prop><d:displayname>tbc-backups</d:displayname></d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/user/tbc-recordings/tbc-backups/old.tbcbackup</d:href>
    <d:propstat><d:prop><d:getlastmodified>Wed, 21 Oct 2015 07:28:00 GMT</d:getlastmodified></d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/user/tbc-recordings/tbc-backups/new.tbcbackup</d:href>
    <d:propstat><d:prop><d:getlastmodified>Thu, 22 Oct 2015 07:28:00 GMT</d:getlastmodified></d:prop></d:propstat>
  </d:response>
</d:multistatus>"""


def _fake_response(*, body: bytes = b"", headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock()
    response.read.return_value = body
    response.headers = MagicMock()
    response.headers.get.side_effect = lambda key, default=None: (headers or {}).get(key, default)
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class WebdavAuthTests(unittest.TestCase):
    def test_object_url_joins_base_and_key(self):
        url = webdav_client.object_url(TARGET, "20260101-cam1.mp4")
        self.assertEqual(url, "https://cloud.example.invalid/remote.php/dav/files/user/tbc-recordings/20260101-cam1.mp4")

    def test_no_auth_header_without_username(self):
        headers = webdav_client._auth_header({"webdav_url": "https://x.invalid"})
        self.assertEqual(headers, {})

    def test_basic_auth_header_with_username(self):
        headers = webdav_client._auth_header(TARGET)
        self.assertTrue(headers["Authorization"].startswith("Basic "))


class WebdavUploadDeleteTests(unittest.TestCase):
    def test_upload_puts_file_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_file = Path(tmp) / "clip.mp4"
            local_file.write_bytes(b"video-bytes")
            with patch("app.tbc.webdav_client.urlopen", return_value=_fake_response()) as urlopen:
                webdav_client.upload(TARGET, local_file, "clip.mp4")
            request = urlopen.call_args.args[0]
            self.assertEqual(request.get_method(), "PUT")
            self.assertEqual(request.data, b"video-bytes")
            self.assertTrue(request.full_url.endswith("/clip.mp4"))

    def test_delete_ignores_404(self):
        with patch("app.tbc.webdav_client.urlopen", side_effect=HTTPError("url", 404, "not found", {}, None)):
            webdav_client.delete(TARGET, "missing.mp4")  # must not raise

    def test_delete_reraises_other_errors(self):
        with patch("app.tbc.webdav_client.urlopen", side_effect=HTTPError("url", 500, "boom", {}, None)):
            with self.assertRaises(HTTPError):
                webdav_client.delete(TARGET, "clip.mp4")


class WebdavDownloadStreamTests(unittest.TestCase):
    def test_streams_chunks_and_reports_length_and_type(self):
        response = _fake_response(body=b"", headers={"Content-Length": "11", "Content-Type": "video/mp4"})
        response.read.side_effect = [b"video-bytes", b""]
        with patch("app.tbc.webdav_client.urlopen", return_value=response):
            chunks, length, content_type = webdav_client.download_stream(TARGET, "clip.mp4")
            collected = b"".join(chunks)
        self.assertEqual(collected, b"video-bytes")
        self.assertEqual(length, 11)
        self.assertEqual(content_type, "video/mp4")

    def test_missing_content_length_reports_none(self):
        response = _fake_response(body=b"", headers={})
        response.read.side_effect = [b""]
        with patch("app.tbc.webdav_client.urlopen", return_value=response):
            _chunks, length, _content_type = webdav_client.download_stream(TARGET, "clip.mp4")
        self.assertIsNone(length)


class WebdavListFilesTests(unittest.TestCase):
    def test_lists_files_and_skips_the_collection_itself(self):
        with patch("app.tbc.webdav_client.urlopen", return_value=_fake_response(body=_PROPFIND_BODY)):
            entries = webdav_client.list_files(TARGET, "tbc-backups")
        names = {entry.name for entry in entries}
        self.assertEqual(names, {"old.tbcbackup", "new.tbcbackup"})

    def test_parses_last_modified_for_sorting(self):
        with patch("app.tbc.webdav_client.urlopen", return_value=_fake_response(body=_PROPFIND_BODY)):
            entries = webdav_client.list_files(TARGET, "tbc-backups")
        by_name = {entry.name: entry.last_modified for entry in entries}
        self.assertLess(by_name["old.tbcbackup"], by_name["new.tbcbackup"])

    def test_returns_empty_list_on_404(self):
        with patch("app.tbc.webdav_client.urlopen", side_effect=HTTPError("url", 404, "not found", {}, None)):
            entries = webdav_client.list_files(TARGET, "tbc-backups")
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
