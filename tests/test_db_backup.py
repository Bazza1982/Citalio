"""Tests for Citalio database backup and restore helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from citalio.db.backup import backup_database, restore_database, validate_citalio_database
from citalio.db.connection import open_and_migrate
from citalio.db.models import ReferenceRecord
from citalio.db.repository import CitationRepository


def _count_references(library) -> int:
    conn = open_and_migrate(library)
    try:
        return conn.execute('SELECT COUNT(*) FROM "references"').fetchone()[0]
    finally:
        conn.close()


def test_backup_and_restore_round_trip(tmp_path):
    library = tmp_path / "library"
    conn = open_and_migrate(library)
    try:
        repo = CitationRepository(conn)
        repo.create_reference(ReferenceRecord(title="Before Backup", citekey="before2026"))
    finally:
        conn.close()

    backup = backup_database(library, label="checkpoint")

    conn = open_and_migrate(library)
    try:
        repo = CitationRepository(conn)
        repo.create_reference(ReferenceRecord(title="After Backup", citekey="after2026"))
    finally:
        conn.close()

    assert _count_references(library) == 2

    result = restore_database(library, Path(backup.backup_path))

    assert _count_references(library) == 1
    assert "citalio_before_restore" in result.pre_restore_backup_path
    validate_citalio_database(tmp_path / "library" / "citalio.db")


def test_backup_to_explicit_output_file(tmp_path):
    library = tmp_path / "library"
    conn = open_and_migrate(library)
    conn.close()

    output = tmp_path / "save-as.db"
    result = backup_database(library, output=output)

    assert result.backup_path == str(output)
    validate_citalio_database(output)


def test_restore_rejects_invalid_backup_without_changing_db(tmp_path):
    library = tmp_path / "library"
    conn = open_and_migrate(library)
    try:
        CitationRepository(conn).create_reference(
            ReferenceRecord(title="Still Here", citekey="still2026")
        )
    finally:
        conn.close()
    invalid = tmp_path / "not-a-db.db"
    invalid.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(ValueError):
        restore_database(library, invalid)

    assert _count_references(library) == 1
