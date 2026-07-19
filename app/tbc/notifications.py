from __future__ import annotations

import json
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from . import database


def notify_event(database_path: str, *, event_type: str, title: str, message: str, recording: dict[str, Any] | None = None, public_base_url: str = "") -> None:
    for channel in database.list_notification_channels(database_path):
        if int(channel.get("enabled") or 0) != 1:
            continue
        event_template = database.get_notification_event_template(database_path, channel, event_type)
        if event_template is None or int(event_template.get("enabled") or 0) != 1:
            continue
        try:
            _send(
                channel,
                _render_template(event_template.get("title_template"), title=title, message=message, event_type=event_type),
                _render_template(event_template.get("message_template"), title=title, message=message, event_type=event_type),
                recording,
                public_base_url,
            )
        except Exception:
            # Notification failures should never break recording or health flows.
            continue


def _render_template(template: str | None, *, title: str, message: str, event_type: str) -> str:
    """Replace the deliberately small, documented notification placeholders."""
    rendered = template or ""
    for key, value in {"title": title, "message": message, "event_type": event_type}.items():
        rendered = rendered.replace("{{ " + key + " }}", value).replace("{{" + key + "}}", value)
    return rendered


def _send(channel: dict[str, Any], title: str, message: str, recording: dict[str, Any] | None, public_base_url: str) -> None:
    kind = channel.get("kind")
    if kind == "telegram":
        _telegram(channel, title, message, recording)
    elif kind == "email":
        _email(channel, title, message, recording)
    elif kind == "pushover":
        _pushover(channel, title, message)
    elif kind == "home_assistant":
        _home_assistant(channel, title, message)
    elif kind == "ntfy":
        _ntfy(channel, title, message, recording, public_base_url)
    elif kind == "gotify":
        _gotify(channel, title, message, recording, public_base_url)
    else:
        _webhook(channel, title, message, recording, public_base_url)


def _webhook(channel: dict[str, Any], title: str, message: str, recording: dict[str, Any] | None, public_base_url: str) -> None:
    url = channel.get("url")
    if not url:
        return
    payload = {
        "title": title,
        "message": message,
        "recording_id": recording.get("id") if recording else None,
        "media_url": f"{public_base_url}/recordings/{recording['id']}/media" if public_base_url and recording else None,
        "snapshot_url": f"{public_base_url}/recordings/{recording['id']}/snapshot" if public_base_url and recording else None,
    }
    _post_json(url, payload, token=channel.get("token"))


def _telegram(channel: dict[str, Any], title: str, message: str, recording: dict[str, Any] | None) -> None:
    token = channel.get("token")
    chat_id = channel.get("chat_id")
    if not token or not chat_id:
        return
    text = f"{title}\n{message}"
    snapshot_path = recording.get("snapshot_path") if recording and int(channel.get("include_snapshot") or 0) == 1 else None
    if snapshot_path and Path(snapshot_path).exists():
        boundary = "----tbc-boundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{text}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"snapshot.jpg\"\r\n"
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode("utf-8") + Path(snapshot_path).read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        urllib.request.urlopen(request, timeout=10).read()
    else:
        _post_form(f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id": chat_id, "text": text})


def _email(channel: dict[str, Any], title: str, message: str, recording: dict[str, Any] | None) -> None:
    smtp_host = channel.get("smtp_host")
    if not smtp_host or not channel.get("email_to"):
        return
    email = EmailMessage()
    email["Subject"] = title
    email["From"] = channel.get("email_from") or channel.get("smtp_username") or "tbc@localhost"
    email["To"] = channel.get("email_to")
    email.set_content(message)
    snapshot_path = recording.get("snapshot_path") if recording and int(channel.get("include_snapshot") or 0) == 1 else None
    if snapshot_path and Path(snapshot_path).exists():
        email.add_attachment(Path(snapshot_path).read_bytes(), maintype="image", subtype="jpeg", filename="snapshot.jpg")
    with smtplib.SMTP(smtp_host, int(channel.get("smtp_port") or 587), timeout=10) as smtp:
        smtp.starttls()
        if channel.get("smtp_username"):
            smtp.login(channel.get("smtp_username"), channel.get("smtp_password") or "")
        smtp.send_message(email)


def _pushover(channel: dict[str, Any], title: str, message: str) -> None:
    if not channel.get("token") or not channel.get("url"):
        return
    _post_form("https://api.pushover.net/1/messages.json", {"token": channel["token"], "user": channel["url"], "title": title, "message": message})


def _home_assistant(channel: dict[str, Any], title: str, message: str) -> None:
    base_url = (channel.get("url") or "").rstrip("/")
    token = channel.get("token")
    service = channel.get("ha_service") or "notify.notify"
    if not base_url or not token:
        return
    domain, service_name = service.split(".", 1) if "." in service else ("notify", service)
    _post_json(f"{base_url}/api/services/{domain}/{service_name}", {"title": title, "message": message}, token=token)


def _ntfy(channel: dict[str, Any], title: str, message: str, recording: dict[str, Any] | None, public_base_url: str) -> None:
    """Publishes to a self-hosted (or ntfy.sh) topic. `url` is the full topic URL,
    e.g. https://ntfy.example.com/tbc-alerts - see https://docs.ntfy.sh/publish/."""
    url = channel.get("url")
    if not url:
        return
    headers = {"Title": title, "Priority": "default"}
    if channel.get("token"):
        headers["Authorization"] = f"Bearer {channel['token']}"
    if recording and public_base_url:
        headers["Click"] = f"{public_base_url}/recordings/{recording['id']}/media"
        if int(channel.get("include_snapshot") or 0) == 1:
            headers["Attach"] = f"{public_base_url}/recordings/{recording['id']}/snapshot"
    request = urllib.request.Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
    urllib.request.urlopen(request, timeout=10).read()


def _gotify(channel: dict[str, Any], title: str, message: str, recording: dict[str, Any] | None, public_base_url: str) -> None:
    """Posts to a self-hosted Gotify server. `url` is the server base URL, `token`
    is the application token - see https://gotify.net/api-docs#/message/createMessage."""
    base_url = (channel.get("url") or "").rstrip("/")
    token = channel.get("token")
    if not base_url or not token:
        return
    payload: dict[str, Any] = {"title": title, "message": message, "priority": 5}
    if recording and public_base_url:
        payload["extras"] = {
            "client::notification": {"click": {"url": f"{public_base_url}/recordings/{recording['id']}/media"}}
        }
    request = urllib.request.Request(
        f"{base_url}/message?token={urllib.parse.quote(token)}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(request, timeout=10).read()


def _post_json(url: str, payload: dict[str, Any], token: str | None = None) -> None:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    urllib.request.urlopen(request, timeout=10).read()


def _post_form(url: str, payload: dict[str, Any]) -> None:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    urllib.request.urlopen(request, timeout=10).read()
