"""Backup and restore helpers for Citalio SQLite libraries."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from citalio.db.connection import get_library_root, open_and_migrate


DB_NAME = "citalio.db"


@dataclass
class BackupResult:
    source_db: str
    backup_path: str


@dataclass
class RestoreResult:
    restored_db: str
    backup_path: str
    pre_restore_backup_path: str


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")


def _safe_label(label: str | None) -> str:
    if not label:
        return ""
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", label.strip()).strip("-._")
    return f"_{value}" if value else ""


def _default_backup_path(root: Path, prefix: str, label: str | None = None) -> Path:
    return root / "backups" / f"{prefix}_{_timestamp()}{_safe_label(label)}.db"


def _resolve_output(root: Path, output: Path | None, label: str | None = None) -> Path:
    if output is None:
        return _default_backup_path(root, "citalio_backup", label)
    if output.exists() and output.is_dir():
        return output / _default_backup_path(root, "citalio_backup", label).name
    if output.suffix:
        return output
    return output / _default_backup_path(root, "citalio_backup", label).name


def copy_sqlite_database(source: Path, destination: Path) -> None:
    """Copy a SQLite database using the online backup API."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(source))
    try:
        dst = sqlite3.connect(str(destination))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def validate_citalio_database(path: Path) -> None:
    """Raise ValueError if *path* is not a valid Citalio SQLite database."""
    if not path.exists():
        raise ValueError(f"Backup file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Backup path is not a file: {path}")

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"SQLite integrity check failed: {integrity}")
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            ).fetchone()
            if row is None:
                raise ValueError("Backup is missing Citalio schema_version table.")
            conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"Backup is not a readable SQLite database: {path}") from exc


def backup_database(
    library: Path | None = None,
    *,
    output: Path | None = None,
    label: str | None = None,
    overwrite: bool = False,
) -> BackupResult:
    """Create a backup copy of the active Citalio database."""
    root = get_library_root(library)
    conn = open_and_migrate(library)
    conn.close()

    source_db = root / DB_NAME
    backup_path = _resolve_output(root, output, label)
    if backup_path.exists() and not overwrite:
        raise FileExistsError(f"Backup path already exists: {backup_path}")

    copy_sqlite_database(source_db, backup_path)
    validate_citalio_database(backup_path)
    return BackupResult(source_db=str(source_db), backup_path=str(backup_path))


def restore_database(
    library: Path | None,
    backup_path: Path,
) -> RestoreResult:
    """Restore Citalio from *backup_path*, after making a pre-restore backup."""
    validate_citalio_database(backup_path)

    root = get_library_root(library)
    conn = open_and_migrate(library)
    conn.close()

    target_db = root / DB_NAME
    pre_restore_backup = _default_backup_path(root, "citalio_before_restore")
    copy_sqlite_database(target_db, pre_restore_backup)
    validate_citalio_database(pre_restore_backup)

    copy_sqlite_database(backup_path, target_db)
    validate_citalio_database(target_db)

    return RestoreResult(
        restored_db=str(target_db),
        backup_path=str(backup_path),
        pre_restore_backup_path=str(pre_restore_backup),
    )
