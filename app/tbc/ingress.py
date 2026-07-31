"""Home Assistant Ingress support.

Ingress proxies every request through a per-installation, dynamically
assigned path prefix (e.g. `/api/hassio_ingress/<token>/...`). Home
Assistant Supervisor's own proxy (`supervisor/api/ingress.py`,
`_create_url`) strips that prefix from the path *before* forwarding to the
add-on's container - the container only ever sees the plain path
(`/cameras`, `/static/i18n.js`, ...) - and separately sends the prefix via
the `X-Ingress-Path` request header, purely so the app can reconstruct
correct absolute URLs when it needs to.

This deliberately does NOT set ASGI `scope["root_path"]`. That looks like
the "correct" mechanism at first (it's what makes Starlette's own
`url_for()`/`Request.url` prefix-aware), but it assumes `scope["path"]`
*already contains* the root_path prefix as a literal substring - true for a
`uvicorn --root-path` deployment behind a proxy that forwards the full
original path, false here, since Supervisor already stripped it. Setting a
root_path that doesn't actually prefix `path` breaks `Mount` routes
specifically (`StaticFiles`, the `/mcp` sub-app): `Mount.matches()`
unconditionally appends its own matched segment to `root_path` for the
child scope, and the mounted app then computes its own path via
`get_route_path()`, which (correctly, given root_path lies about being a
real prefix) returns the *entire unstripped* path again - so `StaticFiles`
ends up looking for `static/static/i18n.js` instead of `static/i18n.js`
and 404s. Confirmed via Starlette's own `starlette/routing.py:get_route_path`
and `Mount.matches`.

Given that, every outgoing URL this app emits is prefixed manually instead
(plain string concatenation, not `url_for()`): this middleware only
rewrites response headers (`Location`, `Set-Cookie`) and exposes
`request.state.ingress_prefix` for templates/JSON payloads/JS to prepend
themselves - see the `ingress_prefix` context processor in main.py and
`{{ ingress_prefix }}/static/...` in templates.

This is a raw ASGI middleware (not `BaseHTTPMiddleware`) so it can rewrite
response headers uniformly no matter which route or helper produced them,
without threading a prefix argument through the ~160 call sites of
`_redirect()`/`RedirectResponse` or reaching into `SessionMiddleware`.

Outside of Home Assistant Ingress (plain Docker, or Home Assistant without
Ingress) no request ever carries `X-Ingress-Path`, so `ingress_prefix` is
always the empty string and every rewrite below is a strict no-op.
"""

from __future__ import annotations

from typing import Any

Scope = dict[str, Any]
Message = dict[str, Any]


def _is_root_relative(path: str) -> bool:
    """True for "/foo" style paths - false for "//foo" (protocol-relative,
    i.e. an off-site URL) and false for absolute "http(s)://..." URLs such
    as the app's presigned S3 recording links, which must never be
    prefixed."""
    return path.startswith("/") and not path.startswith("//")


class IngressPathMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        ingress_prefix = ""
        for name, value in scope.get("headers", ()):
            if name == b"x-ingress-path":
                ingress_prefix = value.decode("latin-1").rstrip("/")
                break

        scope.setdefault("state", {})["ingress_prefix"] = ingress_prefix

        if not ingress_prefix:
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    _rewrite_header(name, value, ingress_prefix) for name, value in message.get("headers", [])
                ]
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _rewrite_header(name: bytes, value: bytes, ingress_prefix: str) -> tuple[bytes, bytes]:
    if name == b"location":
        location = value.decode("latin-1")
        if _is_root_relative(location):
            return (name, f"{ingress_prefix}{location}".encode("latin-1"))
        return (name, value)
    if name == b"set-cookie":
        return (name, _rewrite_cookie_path(value, ingress_prefix))
    return (name, value)


def _rewrite_cookie_path(set_cookie: bytes, ingress_prefix: str) -> bytes:
    """Prefix a `Set-Cookie` header's `Path=` attribute.

    Without this, the session cookie (always `Path=/` -
    see `SessionMiddleware` in main.py) would be sent by the browser on
    every request to the ingress origin, including Home Assistant's own UI
    and every other add-on's ingress traffic on the same host - a real
    cross-add-on cookie scope leak, not just a broken-link issue.
    """
    parts = [part.strip() for part in set_cookie.decode("latin-1").split(";")]
    rewritten = False
    for index, part in enumerate(parts):
        if part.lower().startswith("path="):
            cookie_path = part[len("path="):]
            if _is_root_relative(cookie_path):
                parts[index] = f"Path={ingress_prefix}{cookie_path}"
                rewritten = True
            break
    if not rewritten:
        parts.append(f"Path={ingress_prefix}/")
    return "; ".join(parts).encode("latin-1")
