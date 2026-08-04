import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

from app.tbc import notifications


def _fake_response() -> MagicMock:
    response = MagicMock()
    response.read.return_value = b"{}"
    return response


class SlackNotificationTests(unittest.TestCase):
    def test_plain_message_without_snapshot(self):
        channel = {"kind": "slack", "url": "https://hooks.slack.com/services/x", "include_snapshot": 0}
        with patch("urllib.request.urlopen", return_value=_fake_response()) as urlopen:
            notifications.send_via_channel(channel, "Clip saved", "Driveway")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, channel["url"])
        payload = json.loads(request.data)
        self.assertIn("Clip saved", payload["text"])
        self.assertNotIn("blocks", payload)

    def test_snapshot_link_included_when_enabled(self):
        channel = {"kind": "slack", "url": "https://hooks.slack.com/services/x", "include_snapshot": 1}
        recording = {"id": 42}
        with patch("urllib.request.urlopen", return_value=_fake_response()) as urlopen:
            notifications.send_via_channel(channel, "Clip saved", "Driveway", recording, "https://tbc.example.invalid")
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertIn("blocks", payload)
        image_block = next(block for block in payload["blocks"] if block["type"] == "image")
        self.assertEqual(image_block["image_url"], "https://tbc.example.invalid/recordings/42/snapshot")

    def test_no_url_sends_nothing(self):
        with patch("urllib.request.urlopen") as urlopen:
            notifications.send_via_channel({"kind": "slack"}, "Title", "Message")
        urlopen.assert_not_called()


class DiscordNotificationTests(unittest.TestCase):
    def test_plain_message_uses_content_field(self):
        channel = {"kind": "discord", "url": "https://discord.com/api/webhooks/x", "include_snapshot": 0}
        with patch("urllib.request.urlopen", return_value=_fake_response()) as urlopen:
            notifications.send_via_channel(channel, "Clip saved", "Driveway")
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertIn("Clip saved", payload["content"])
        self.assertNotIn("embeds", payload)

    def test_snapshot_embed_included_when_enabled(self):
        channel = {"kind": "discord", "url": "https://discord.com/api/webhooks/x", "include_snapshot": 1}
        recording = {"id": 7}
        with patch("urllib.request.urlopen", return_value=_fake_response()) as urlopen:
            notifications.send_via_channel(channel, "Clip saved", "Driveway", recording, "https://tbc.example.invalid")
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["embeds"][0]["image"]["url"], "https://tbc.example.invalid/recordings/7/snapshot")


class MatrixNotificationTests(unittest.TestCase):
    def test_sends_authenticated_put_to_room(self):
        channel = {
            "kind": "matrix",
            "url": "https://matrix.example.invalid",
            "token": "syt_abc",
            "chat_id": "!room:example.invalid",
        }
        with patch("urllib.request.urlopen", return_value=_fake_response()) as urlopen:
            notifications.send_via_channel(channel, "Clip saved", "Driveway")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(request.get_header("Authorization"), "Bearer syt_abc")
        self.assertIn(unquote("!room:example.invalid"), unquote(request.full_url))
        self.assertTrue(request.full_url.startswith("https://matrix.example.invalid/_matrix/client/v3/rooms/"))
        payload = json.loads(request.data)
        self.assertEqual(payload["msgtype"], "m.text")
        self.assertIn("Driveway", payload["body"])

    def test_missing_room_id_sends_nothing(self):
        channel = {"kind": "matrix", "url": "https://matrix.example.invalid", "token": "syt_abc"}
        with patch("urllib.request.urlopen") as urlopen:
            notifications.send_via_channel(channel, "Title", "Message")
        urlopen.assert_not_called()


class SignalNotificationTests(unittest.TestCase):
    def test_sends_to_signal_cli_rest_api(self):
        channel = {
            "kind": "signal",
            "url": "http://signal-cli-rest-api:8080",
            "sender_id": "+491234567890",
            "chat_id": "+499876543210",
        }
        with patch("urllib.request.urlopen", return_value=_fake_response()) as urlopen:
            notifications.send_via_channel(channel, "Clip saved", "Driveway")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://signal-cli-rest-api:8080/v2/send")
        payload = json.loads(request.data)
        self.assertEqual(payload["number"], "+491234567890")
        self.assertEqual(payload["recipients"], ["+499876543210"])
        self.assertIn("Driveway", payload["message"])
        self.assertIsNone(request.get_header("Authorization"))

    def test_optional_bearer_token_is_forwarded(self):
        channel = {
            "kind": "signal",
            "url": "http://signal-cli-rest-api:8080",
            "sender_id": "+491234567890",
            "chat_id": "+499876543210",
            "token": "proxy-secret",
        }
        with patch("urllib.request.urlopen", return_value=_fake_response()) as urlopen:
            notifications.send_via_channel(channel, "Title", "Message")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer proxy-secret")

    def test_missing_sender_sends_nothing(self):
        channel = {"kind": "signal", "url": "http://signal-cli-rest-api:8080", "chat_id": "+499876543210"}
        with patch("urllib.request.urlopen") as urlopen:
            notifications.send_via_channel(channel, "Title", "Message")
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
