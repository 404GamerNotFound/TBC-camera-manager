from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from markupsafe import Markup


def tojson_html_safe(value: Any) -> Markup:
    """JSON-encode a value for embedding in an HTML attribute.

    Escapes `<`, `>`, `&`, and `'` so the result is safe inside single- or
    double-quoted attributes alike (matching Flask's own `tojson` filter) -
    a JSON string is otherwise free to contain any of these unescaped, which
    would break out of a single-quoted attribute such as
    `data-i18n-params='{{ params | tojson }}'`.
    """
    return Markup(
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("'", "\\u0027")
    )


def format_timestamp(value: Any, preferences: dict[str, Any] | None = None) -> str:
    """Format an application timestamp according to the saved UI preferences.

    Database timestamps are UTC by convention. Older integrations may send
    ISO timestamps with an explicit offset, which is preserved before the
    selected display timezone is applied. Unparseable values stay visible
    unchanged instead of turning a useful diagnostic into an empty cell.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        timestamp = value
    else:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return str(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    requested_timezone = str((preferences or {}).get("timezone") or "Europe/Berlin")
    try:
        timestamp = timestamp.astimezone(ZoneInfo(requested_timezone))
    except ZoneInfoNotFoundError:
        timestamp = timestamp.astimezone(ZoneInfo("Europe/Berlin"))

    date_format = str((preferences or {}).get("date_format") or "de")
    date_pattern = {"de": "%d.%m.%Y", "iso": "%Y-%m-%d", "us": "%m/%d/%Y"}.get(
        date_format, "%d.%m.%Y"
    )
    time_format = str((preferences or {}).get("time_format") or "24h")
    show_seconds = bool((preferences or {}).get("show_seconds"))
    if time_format == "12h":
        time_pattern = "%I:%M:%S %p" if show_seconds else "%I:%M %p"
        formatted_time = timestamp.strftime(time_pattern).lstrip("0")
    else:
        formatted_time = timestamp.strftime("%H:%M:%S" if show_seconds else "%H:%M")
    return f"{timestamp.strftime(date_pattern)} {formatted_time}"
