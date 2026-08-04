"""Minimal WebDAV client for the "webdav" storage-target kind.

Hand-rolled over ``urllib`` instead of a ``webdavclient3``/``requests`` dependency,
matching how the rest of this codebase talks to simple HTTP APIs (see
notifications.py) - a storage destination only needs PUT/GET/DELETE/PROPFIND, and
stdlib ``xml.etree`` is enough for the tiny, fixed PROPFIND response shape used here.
"""
from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

_DAV_NS = "{DAV:}"


@dataclass(frozen=True)
class WebdavEntry:
    href: str
    name: str
    last_modified: datetime | None


def _base_url(target: dict[str, Any]) -> str:
    base = str(target.get("webdav_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("The selected WebDAV storage target has no URL configured.")
    return base


def _auth_header(target: dict[str, Any]) -> dict[str, str]:
    username = target.get("webdav_username")
    if not username:
        return {}
    password = target.get("webdav_password") or ""
    credentials = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {credentials}"}


def object_url(target: dict[str, Any], remote_key: str) -> str:
    return urljoin(_base_url(target) + "/", quote(remote_key.lstrip("/")))


def upload(target: dict[str, Any], local_path: str | Path, remote_key: str) -> None:
    """Uploads a local file via PUT.

    The destination folder must already exist - WebDAV servers vary too much in
    collection (MKCOL) semantics to auto-create it reliably, matching how the S3
    storage kind also requires a pre-existing bucket rather than creating one.
    """
    data = Path(local_path).read_bytes()
    request = Request(object_url(target, remote_key), data=data, method="PUT", headers=_auth_header(target))
    urlopen(request, timeout=60).close()  # noqa: S310 - target URL is admin-configured, not user input


def delete(target: dict[str, Any], remote_key: str) -> None:
    request = Request(object_url(target, remote_key), method="DELETE", headers=_auth_header(target))
    try:
        urlopen(request, timeout=30).close()  # noqa: S310
    except HTTPError as exc:
        if exc.code != 404:
            raise


def download_stream(target: dict[str, Any], remote_key: str, *, chunk_size: int = 65536) -> tuple[Iterator[bytes], int | None, str]:
    """Returns (chunk_iterator, content_length, content_type) for proxying a GET
    response back to the browser.

    Unlike S3, plain WebDAV (Basic Auth on every request) has no presigned-URL
    concept a browser could be redirected to, so the app streams the bytes through
    itself instead - see routers/recordings.py's media/snapshot/download routes.
    """
    request = Request(object_url(target, remote_key), method="GET", headers=_auth_header(target))
    response = urlopen(request, timeout=30)  # noqa: S310
    length = response.headers.get("Content-Length")
    content_type = response.headers.get("Content-Type") or "application/octet-stream"

    def _iterate() -> Iterator[bytes]:
        with response:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    return _iterate(), (int(length) if length else None), content_type


def list_files(target: dict[str, Any], prefix: str = "") -> list[WebdavEntry]:
    """Lists the files directly under `prefix` via a depth-1 PROPFIND.

    Used to prune old external backups, mirroring how backup.py's S3 path lists and
    prunes bucket objects under a prefix.
    """
    collection_url = object_url(target, f"{prefix.rstrip('/')}/") if prefix else _base_url(target) + "/"
    body = b'<?xml version="1.0" encoding="utf-8"?><propfind xmlns="DAV:"><prop><displayname/><getlastmodified/></prop></propfind>'
    request = Request(
        collection_url,
        data=body,
        method="PROPFIND",
        headers={**_auth_header(target), "Depth": "1", "Content-Type": "application/xml"},
    )
    try:
        response = urlopen(request, timeout=30)  # noqa: S310
    except HTTPError as exc:
        if exc.code == 404:
            return []
        raise
    with response:
        root = ET.fromstring(response.read())  # noqa: S314 - trusted, admin-configured WebDAV server

    entries: list[WebdavEntry] = []
    for response_el in root.findall(f"{_DAV_NS}response"):
        href_el = response_el.find(f"{_DAV_NS}href")
        if href_el is None or not href_el.text:
            continue
        href = href_el.text
        if href.rstrip("/") == collection_url.rstrip("/") or href.endswith("/"):
            continue  # the collection itself, or a nested sub-folder
        last_modified_el = response_el.find(f".//{_DAV_NS}getlastmodified")
        entries.append(
            WebdavEntry(
                href=href,
                name=href.rstrip("/").rsplit("/", 1)[-1],
                last_modified=_parse_http_date(last_modified_el.text) if last_modified_el is not None else None,
            )
        )
    return entries


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
