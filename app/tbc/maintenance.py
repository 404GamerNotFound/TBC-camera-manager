from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import database
from .recording import delete_recording_files


def storage_overview(database_path: str) -> list[dict[str, Any]]:
    targets = database.list_storage_targets(database_path)
    rows: list[dict[str, Any]] = []
    for target in targets:
        local_path = target.get("local_path")
        used_bytes = _recording_bytes_for_storage(database_path, int(target["id"]))
        free_bytes = None
        total_bytes = None
        if target["kind"] == "local" and local_path:
            path = Path(local_path)
            path.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(path)
            free_bytes = usage.free
            total_bytes = usage.total
        rows.append(
            {
                **target,
                "used_bytes": used_bytes,
                "free_bytes": free_bytes,
                "total_bytes": total_bytes,
            }
        )
    return rows


def cleanup_preview(database_path: str) -> list[dict[str, Any]]:
    recordings = database.list_ready_recordings_for_cleanup(database_path)
    rules = _effective_retention_rules(database_path)
    selected: dict[int, dict[str, Any]] = {}
    now = datetime.utcnow()

    for rule in rules:
        matching = [_add_reason(recording, rule) for recording in recordings if _matches_rule(recording, rule)]
        max_age_days = rule.get("max_age_days")
        if max_age_days not in (None, ""):
            cutoff = now - timedelta(days=int(max_age_days))
            for recording in matching:
                if _parse_dt(recording.get("started_at")) < cutoff:
                    selected[int(recording["id"])] = {**recording, "cleanup_reason": f"älter als {max_age_days} Tage"}

        max_size_gb = rule.get("max_size_gb")
        if max_size_gb not in (None, ""):
            limit_bytes = int(float(max_size_gb) * 1024**3)
            kept: list[dict[str, Any]] = []
            total = 0
            for recording in sorted(matching, key=lambda item: str(item.get("started_at") or ""), reverse=True):
                size = int(recording.get("size_bytes") or 0)
                if total + size <= limit_bytes:
                    kept.append(recording)
                    total += size
                else:
                    selected[int(recording["id"])] = {**recording, "cleanup_reason": f"über {max_size_gb} GB Limit"}

    return sorted(selected.values(), key=lambda item: str(item.get("started_at") or ""))


def apply_cleanup(database_path: str) -> int:
    doomed = cleanup_preview(database_path)
    for recording in doomed:
        full = database.get_recording(database_path, int(recording["id"])) or recording
        delete_recording_files(full)
        database.delete_recording_metadata(database_path, int(recording["id"]))
    return len(doomed)


def _recording_bytes_for_storage(database_path: str, storage_id: int) -> int:
    return sum(
        int(recording.get("size_bytes") or 0)
        for recording in database.list_ready_recordings_for_cleanup(database_path)
        if int(recording.get("storage_id") or 0) == storage_id
    )


def _matches_rule(recording: dict[str, Any], rule: dict[str, Any]) -> bool:
    camera_id = rule.get("camera_id")
    detection_key = rule.get("detection_key")
    storage_id = rule.get("storage_id")
    if camera_id not in (None, "") and int(recording.get("camera_id") or 0) != int(camera_id):
        return False
    if detection_key and recording.get("detection_key") != detection_key:
        return False
    if storage_id not in (None, "") and int(recording.get("storage_id") or 0) != int(storage_id):
        return False
    return True


def _add_reason(recording: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    return {**recording, "rule_name": rule.get("name")}


def _effective_retention_rules(database_path: str) -> list[dict[str, Any]]:
    rules = [rule for rule in database.list_retention_rules(database_path) if int(rule.get("enabled") or 0) == 1]
    for target in database.list_storage_targets(database_path):
        if target.get("retention_days") in (None, "") and target.get("retention_max_gb") in (None, ""):
            continue
        rules.append(
            {
                "name": f"{target['name']} Speicherziel",
                "enabled": 1,
                "storage_id": target["id"],
                "camera_id": None,
                "detection_key": None,
                "max_age_days": target.get("retention_days"),
                "max_size_gb": target.get("retention_max_gb"),
            }
        )
    return rules


def _parse_dt(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.min
