import json
import unittest
from html.parser import HTMLParser

from app.tbc.template_filters import tojson_html_safe


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


if __name__ == "__main__":
    unittest.main()
