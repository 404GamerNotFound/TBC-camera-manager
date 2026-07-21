from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
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
    "restore_backup",
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
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))

    tmp_path = target.with_suffix(target.suffix + ".restore-tmp")
    tmp_path.write_bytes(snapshot)
    _validate_sqlite_file(tmp_path)
    os.replace(tmp_path, target)


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
