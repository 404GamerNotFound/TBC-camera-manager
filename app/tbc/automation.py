"""Automation rules: user-defined conditions that fire an existing notification
channel when a recording-lifecycle or recognition event matches (see
database.py's `automation_rules` table and `list_matching_automation_rules`).

Reuses the existing notification delivery machinery (`notifications.send_via_channel`,
`notifications.render_template`) instead of duplicating it - the only new logic here
is condition-matching and cooldown bookkeeping. Called right alongside
`notifications.notify_event`, not instead of it.
"""
from __future__ import annotations

import logging
from typing import Any

from . import database, notifications

LOGGER = logging.getLogger(__name__)


def parse_identity_filter(identity: str | None) -> tuple[int | None, int | None, bool]:
    """Splits a single "identity" form/query value into (matched_face_id, matched_plate_id,
    unknown_only) - encoded as "face:<id>", "plate:<id>", "unknown", or empty for "any".
    Shared by the /recognition search filter and the /automations rule editor - both offer
    the same "known face, known plate, unknown, or any" choice over the same encoding.
    """
    if not identity:
        return None, None, False
    if identity == "unknown":
        return None, None, True
    kind, _, raw_id = identity.partition(":")
    if not raw_id.isdigit():
        return None, None, False
    if kind == "face":
        return int(raw_id), None, False
    if kind == "plate":
        return None, int(raw_id), False
    return None, None, False


def evaluate_and_fire(
    database_path: str,
    *,
    source: str,
    camera_id: int,
    title: str,
    message: str,
    event_type: str | None = None,
    kind: str | None = None,
    matched_face_id: int | None = None,
    matched_plate_id: int | None = None,
    label: str = "",
    recording: dict[str, Any] | None = None,
    public_base_url: str = "",
) -> None:
    rules = database.list_matching_automation_rules(
        database_path,
        source=source,
        camera_id=camera_id,
        event_type=event_type,
        kind=kind,
        matched_face_id=matched_face_id,
        matched_plate_id=matched_plate_id,
    )
    for rule in rules:
        try:
            _fire_rule(
                database_path,
                rule,
                title=title,
                message=message,
                event_type=event_type or kind or source,
                label=label,
                recording=recording,
                public_base_url=public_base_url,
            )
        except Exception:
            # One misconfigured rule/channel must never block the others, same
            # guarantee notify_event already gives built-in notifications.
            LOGGER.exception("Automation rule %s failed to fire", rule.get("id"))


def _fire_rule(
    database_path: str,
    rule: dict[str, Any],
    *,
    title: str,
    message: str,
    event_type: str,
    label: str,
    recording: dict[str, Any] | None,
    public_base_url: str,
) -> None:
    if not database.try_fire_automation_rule(
        database_path, int(rule["id"]), cooldown_seconds=int(rule.get("cooldown_seconds") or 0)
    ):
        return
    channel = database.get_notification_channel(database_path, int(rule["notification_channel_id"]))
    if channel is None or int(channel.get("enabled") or 0) != 1:
        return
    rendered_title = notifications.render_template(
        rule.get("title_template"), title=title, message=message, event_type=event_type, label=label
    )
    rendered_message = notifications.render_template(
        rule.get("message_template"), title=title, message=message, event_type=event_type, label=label
    )
    notifications.send_via_channel(channel, rendered_title, rendered_message, recording, public_base_url)
