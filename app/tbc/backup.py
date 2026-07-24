from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .security import SecretDecryptionError, decrypt_bytes, encrypt_bytes

MANIFEST_APP = "tbc-camera-manager"
MANIFEST_FORMAT = 1
DB_ENTRY_NAME = "tbc.sqlite3"
MANIFEST_ENTRY_NAME = "manifest.json"

BACKUP_EXTENSION = ".tbcbackup"

__all__ = [
    "BackupError",
    "backup_filename",
    "create_backup",
    "create_backup_file",
    "get_backup_file",
    "list_backup_files",
    "prune_backup_files",
    "restore_backup",
    "run_scheduled_backup",
    "schedule_is_due",
]


class BackupError(RuntimeError):
    """Raised for backup/restore failures the caller should surface to the admin."""


def create_backup(database_path: str, secret_key: str) -> bytes:
    """Create an encrypted backup archive of the database.

    Uses sqlite3's online backup API so this is safe to run against a live,
    WAL-mode database without pausing the app.
    """
    snapshot = _snapshot_database(database_path)
    manifest = {
        "app": MANIFEST_APP,
        "format": MANIFEST_FORMAT,
        "version": __version__,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_ENTRY_NAME, json.dumps(manifest))
        archive.writestr(DB_ENTRY_NAME, snapshot)
    return encrypt_bytes(secret_key, buffer.getvalue())


def backup_filename(created_at: datetime | None = None) -> str:
    """Return the human-readable, filesystem-safe name used for local backups."""
    timestamp = created_at or datetime.now().astimezone()
    return f"TBC_v{__version__}_{timestamp.strftime('%Y-%m-%d-%H-%M-%S')}{BACKUP_EXTENSION}"


def create_backup_file(database_path: str, secret_key: str, backups_path: str) -> Path:
    """Create a backup and persist it locally in the configured backup directory."""
    archive = create_backup(database_path, secret_key)
    directory = Path(backups_path)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for sequence in range(1000):
            suffix = "" if sequence == 0 else f"-{sequence:02d}"
            filename = backup_filename()
            target = directory / f"{filename.removesuffix(BACKUP_EXTENSION)}{suffix}{BACKUP_EXTENSION}"
            try:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            with os.fdopen(descriptor, "wb") as output:
                output.write(archive)
                output.flush()
                os.fsync(output.fileno())
            return target
    except OSError as exc:
        raise BackupError(f"The backup could not be saved locally: {exc}") from exc
    raise BackupError("Could not create a unique backup file name.")


def list_backup_files(backups_path: str) -> list[dict[str, Any]]:
    """List locally stored backup archives, newest first, without exposing paths."""
    directory = Path(backups_path)
    if not directory.is_dir():
        return []
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and not path.is_symlink() and path.suffix == BACKUP_EXTENSION
    ]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "filename": path.name,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "size_label": _format_file_size(path.stat().st_size),
        }
        for path in files
    ]


def get_backup_file(backups_path: str, filename: str) -> Path | None:
    """Resolve one local backup while rejecting traversal and unrelated files."""
    candidate = Path(filename)
    if candidate.name != filename or candidate.suffix != BACKUP_EXTENSION:
        return None
    directory = Path(backups_path)
    path = directory / candidate.name
    if path.is_symlink() or not path.is_file():
        return None
    return path if path.resolve().parent == directory.resolve() else None


def schedule_is_due(schedule: dict[str, Any], now: datetime | None = None) -> bool:
    """Return whether an enabled backup schedule needs to run.

    The timestamp is persisted only after a completed attempt. This prevents a
    broken external target from causing a backup attempt on every loop tick.
    """
    if not schedule.get("enabled"):
        return False
    interval_hours = int(schedule.get("interval_hours") or 24)
    last_run_at = schedule.get("last_run_at")
    if not last_run_at:
        return True
    try:
        last_run = datetime.fromisoformat(str(last_run_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    current_time = now or datetime.now(timezone.utc)
    return current_time >= last_run + timedelta(hours=interval_hours)


def prune_backup_files(backups_path: str, retain_count: int) -> int:
    """Keep the newest encrypted backup files and return how many were removed."""
    keep = _validated_retain_count(retain_count)
    directory = Path(backups_path)
    if not directory.is_dir():
        return 0
    files = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and not path.is_symlink() and path.suffix == BACKUP_EXTENSION
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for path in files[keep:]:
        path.unlink()
        removed += 1
    return removed


def run_scheduled_backup(
    database_path: str,
    secret_key: str,
    backups_path: str,
    *,
    retain_count: int,
    storage_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create, retain and optionally replicate one encrypted backup.

    A local archive is deliberately retained even when an external target is
    selected. This makes a restore possible when S3 or a network mount is
    temporarily unavailable. External copies are isolated below
    ``tbc-backups`` so recordings can never be included in retention cleanup.
    """
    saved_backup = create_backup_file(database_path, secret_key, backups_path)
    local_removed = prune_backup_files(backups_path, retain_count)
    result: dict[str, Any] = {
        "filename": saved_backup.name,
        "local_path": str(saved_backup),
        "local_removed": local_removed,
        "external_location": None,
        "external_removed": 0,
    }
    if storage_target is None:
        return result

    try:
        external_location = _copy_to_external_target(saved_backup, storage_target)
        external_removed = _prune_external_target(storage_target, retain_count)
    except (OSError, RuntimeError) as exc:
        raise BackupError(f"The local backup was created, but the external copy failed: {exc}") from exc
    result["external_location"] = external_location
    result["external_removed"] = external_removed
    return result


def _copy_to_external_target(local_file: Path, target: dict[str, Any]) -> str:
    kind = target.get("kind")
    if kind == "local":
        base_path = target.get("local_path")
        if not base_path:
            raise RuntimeError("The selected local storage target has no path.")
        directory = Path(str(base_path)) / "tbc-backups"
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / local_file.name
        if destination.resolve() != local_file.resolve():
            shutil.copyfile(local_file, destination)
            os.chmod(destination, 0o600)
        return str(destination)
    if kind == "s3":
        bucket = target.get("s3_bucket")
        if not bucket:
            raise RuntimeError("The selected S3 storage target has no bucket.")
        key = _s3_backup_prefix(target) + "/" + local_file.name
        _s3_client(target).upload_file(str(local_file), bucket, key)
        return f"s3://{bucket}/{key}"
    raise RuntimeError("The selected storage target is not supported for backups.")


def _prune_external_target(target: dict[str, Any], retain_count: int) -> int:
    keep = _validated_retain_count(retain_count)
    kind = target.get("kind")
    if kind == "local":
        base_path = target.get("local_path")
        if not base_path:
            raise RuntimeError("The selected local storage target has no path.")
        return prune_backup_files(str(Path(str(base_path)) / "tbc-backups"), keep)
    if kind != "s3":
        raise RuntimeError("The selected storage target is not supported for backups.")
    bucket = target.get("s3_bucket")
    if not bucket:
        raise RuntimeError("The selected S3 storage target has no bucket.")
    client = _s3_client(target)
    prefix = _s3_backup_prefix(target) + "/"
    objects: list[dict[str, Any]] = []
    continuation_token: str | None = None
    while True:
        params: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if continuation_token:
            params["ContinuationToken"] = continuation_token
        page = client.list_objects_v2(**params)
        objects.extend(
            item
            for item in page.get("Contents", [])
            if str(item.get("Key", "")).endswith(BACKUP_EXTENSION)
        )
        if not page.get("IsTruncated"):
            break
        continuation_token = page.get("NextContinuationToken")
        if not continuation_token:
            break
    objects.sort(key=lambda item: item.get("LastModified", datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    for item in objects[keep:]:
        client.delete_object(Bucket=bucket, Key=item["Key"])
    return max(0, len(objects) - keep)


def _s3_backup_prefix(target: dict[str, Any]) -> str:
    prefix = str(target.get("s3_prefix") or "").strip("/")
    return f"{prefix}/tbc-backups" if prefix else "tbc-backups"


def _s3_client(target: dict[str, Any]):
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is not installed for S3 storage destinations") from exc
    return boto3.client(
        "s3",
        endpoint_url=target.get("s3_endpoint_url") or None,
        region_name=target.get("s3_region") or None,
        aws_access_key_id=target.get("s3_access_key_id") or None,
        aws_secret_access_key=target.get("s3_secret_access_key") or None,
    )


def _validated_retain_count(retain_count: int) -> int:
    try:
        value = int(retain_count)
    except (TypeError, ValueError) as exc:
        raise BackupError("The number of retained backups must be a whole number.") from exc
    if not 1 <= value <= 365:
        raise BackupError("The number of retained backups must be between 1 and 365.")
    return value


def restore_backup(data: bytes, database_path: str, secret_key: str) -> None:
    """Restore a database from a backup archive created by create_backup().

    The current database file is copied to `<database_path>.bak` first, so a
    failed or unwanted restore can be undone by hand. The live app does not
    hot-swap its open connections; callers should tell the admin to restart
    the app/container after this returns.
    """
    try:
        decrypted = decrypt_bytes(secret_key, data)
    except SecretDecryptionError as exc:
        raise BackupError(str(exc)) from exc

    try:
        with zipfile.ZipFile(io.BytesIO(decrypted)) as archive:
            manifest = json.loads(archive.read(MANIFEST_ENTRY_NAME))
            snapshot = archive.read(DB_ENTRY_NAME)
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise BackupError("This file is not a valid TBC backup archive.") from exc

    if manifest.get("app") != MANIFEST_APP or manifest.get("format") != MANIFEST_FORMAT:
        raise BackupError("This backup archive's format is not recognized by this version of TBC.")

    target = Path(database_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # Snapshot via the online backup API instead of copying the file: the live
        # database runs in WAL mode, so a plain file copy would silently miss every
        # transaction still sitting in the -wal file.
        target.with_suffix(target.suffix + ".bak").write_bytes(_snapshot_database(str(target)))

    tmp_path = target.with_suffix(target.suffix + ".restore-tmp")
    tmp_path.write_bytes(snapshot)
    _validate_sqlite_file(tmp_path)
    os.replace(tmp_path, target)
    # Drop the old database's WAL sidecar files. Left in place, SQLite would try to
    # replay the previous database's write-ahead log into the freshly restored file
    # on next open and corrupt it.
    for suffix in ("-wal", "-shm"):
        Path(str(target) + suffix).unlink(missing_ok=True)


def _snapshot_database(database_path: str) -> bytes:
    """Take a consistent online copy of the database via sqlite3's backup API.

    Safe to call against a live WAL-mode database - this is the same API
    sqlite3's own command-line `.backup` uses, so it doesn't require pausing
    writers.
    """
    import tempfile

    fd, tmp_name = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    try:
        source = sqlite3.connect(database_path)
        dest = sqlite3.connect(tmp_name)
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        return Path(tmp_name).read_bytes()
    finally:
        os.unlink(tmp_name)


def _validate_sqlite_file(path: Path) -> None:
    try:
        connection = sqlite3.connect(str(path))
        try:
            connection.execute("SELECT COUNT(*) FROM sqlite_master")
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        path.unlink(missing_ok=True)
        raise BackupError("The backup's database file is corrupt or unreadable.") from exc


def _format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"
