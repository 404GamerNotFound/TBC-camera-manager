import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from app.tbc import database
from app.tbc.template_filters import format_timestamp, tojson_html_safe


class _SingleAttrParser(HTMLParser):
    """Minimal HTML parser used to verify a value survives being embedded in
    a single-quoted attribute exactly the way base.html embeds flash params:
    `data-i18n-params='{{ params | tojson }}'`."""

    def __init__(self) -> None:
        super().__init__()
        self.attrs: dict[str, str | None] = {}

    def handle_starttag(self, tag, attrs):
        self.attrs.update(attrs)


class TojsonHtmlSafeTests(unittest.TestCase):
    def test_round_trips_through_json(self):
        value = {"message": "go2rtc could not be started"}
        encoded = tojson_html_safe(value)

        self.assertEqual(json.loads(str(encoded)), value)

    def test_escapes_single_quote_so_it_does_not_break_out_of_the_attribute(self):
        # This is the exact shape of the OSError repr Python produces for a
        # failed exec, e.g. "[Errno 8] Exec format error: 'go2rtc'" - the
        # unescaped single quote is what broke the flash message.
        value = {"message": "go2rtc could not be started: [Errno 8] Exec format error: 'go2rtc'"}
        encoded = tojson_html_safe(value)

        self.assertNotIn("'", str(encoded))

        html = f"<div data-i18n-params='{encoded}'></div>"
        parser = _SingleAttrParser()
        parser.feed(html)

        self.assertEqual(json.loads(parser.attrs["data-i18n-params"]), value)

    def test_escapes_angle_brackets_and_ampersand(self):
        value = {"message": "<script>alert(1)</script> & more"}
        encoded = str(tojson_html_safe(value))

        self.assertNotIn("<", encoded)
        self.assertNotIn(">", encoded)
        self.assertNotIn(" & ", encoded)
        self.assertEqual(json.loads(encoded), value)

    def test_returned_value_is_markup_safe(self):
        from markupsafe import Markup

        self.assertIsInstance(tojson_html_safe({"a": 1}), Markup)


class TimestampFormattingTests(unittest.TestCase):
    def test_applies_date_time_timezone_and_seconds_preferences(self):
        self.assertEqual(
            format_timestamp(
                "2026-07-22 14:54:09",
                {
                    "date_format": "de",
                    "time_format": "24h",
                    "timezone": "Europe/Berlin",
                    "show_seconds": True,
                },
            ),
            "22.07.2026 16:54:09",
        )
        self.assertEqual(
            format_timestamp(
                "2026-07-22 14:54:09",
                {
                    "date_format": "us",
                    "time_format": "12h",
                    "timezone": "America/New_York",
                    "show_seconds": False,
                },
            ),
            "07/22/2026 10:54 AM",
        )

    def test_unparseable_timestamp_remains_visible(self):
        self.assertEqual(format_timestamp("camera did not report a time"), "camera did not report a time")


class UiPreferencesDatabaseTests(unittest.TestCase):
    def test_preferences_roundtrip_and_invalid_values_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "tbc.db")
            database.initialize(database_path)
            database.update_ui_preferences(
                database_path,
                date_format="iso",
                time_format="12h",
                timezone="UTC",
                show_seconds=True,
                compact_mode=False,
                dashboard_refresh_seconds=30,
            )
            preferences = database.get_ui_preferences(database_path)
            self.assertEqual(preferences["date_format"], "iso")
            self.assertEqual(preferences["time_format"], "12h")
            self.assertEqual(preferences["timezone"], "UTC")
            self.assertTrue(preferences["show_seconds"])
            self.assertFalse(preferences["compact_mode"])
            self.assertEqual(preferences["dashboard_refresh_seconds"], 30)

            database.update_ui_preferences(
                database_path,
                date_format="invalid",
                time_format="invalid",
                timezone="invalid",
                show_seconds=False,
                compact_mode=True,
                dashboard_refresh_seconds=17,
            )
            preferences = database.get_ui_preferences(database_path)
            self.assertEqual(preferences["date_format"], "de")
            self.assertEqual(preferences["time_format"], "24h")
            self.assertEqual(preferences["timezone"], "Europe/Berlin")
            self.assertEqual(preferences["dashboard_refresh_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
