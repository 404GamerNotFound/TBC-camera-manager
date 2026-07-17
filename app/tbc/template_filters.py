from __future__ import annotations

import json
from typing import Any

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
