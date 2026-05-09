"""Tests for DB connection bootstrap, migration runner, and schema correctness."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from citalio.db.connection import (
    _list_migration_files,
    _version_from_filename,
    apply_migrations,
    open_and_migrate,
    open_db,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _temp_library() -> Path:
    """Return a fresh temporary directory for each test."""
    d = tempfile.mkdtemp(prefix="citalio_test_")
    return Path(d)


# ---------------------------------------------------------------------------
# Migration file discovery
# ---------------------------------------------------------------------------

def test_migration_files_found():
    files = _list_migration_files()
    assert len(files) >= 1, "At least 001_initial_schema.sql must exist"


def test_migration_file_sorted():
    files = _list_migration_files()
    versions = [_version_from_filename(f) for f in files]
    assert versions == sorted(versions), "Migration files must be sorted by version"


def test_version_from_filename():
    from pathlib import Path
    assert _version_from_filename(Path("001_initial_schema.sql")) == 1
    assert _version_from_filename(Path("012_add_render_cache.sql")) == 12


# ---------------------------------------------------------------------------
# open_db: PRAGMAs
# ---------------------------------------------------------------------------

def test_open_db_pragmas():
    lib = _temp_library()
    conn = open_db(lib)
    try:
        wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert wal == "wal", f"Expected WAL, got {wal!r}"

        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 5000, f"Expected 5000ms, got {timeout}"

        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1, "foreign_keys must be ON"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# apply_migrations: idempotency and schema_version
# ---------------------------------------------------------------------------

def test_apply_migrations_creates_schema_version():
    lib = _temp_library()
    conn = open_db(lib)
    try:
        applied = apply_migrations(conn)
        assert 1 in applied, "Migration 001 must be applied on a fresh DB"

        row = conn.execute(
            "SELECT version FROM schema_version WHERE version = 1"
        ).fetchone()
        assert row is not None, "schema_version must record version 1"
    finally:
        conn.close()


def test_apply_migrations_idempotent():
    lib = _temp_library()
    conn = open_db(lib)
    try:
        first = apply_migrations(conn)
        second = apply_migrations(conn)
        assert len(second) == 0, "Second run must apply no migrations"
        assert first == [1]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema tables present after migration
# ---------------------------------------------------------------------------

EXPECTED_TABLES = [
    "schema_version",
    "references",
    "creators",
    "reference_creators",
    "attachments",
    "chunks",
    "notes",
    "tags",
    "reference_tags",
    "collections",
    "collection_items",
    "provenance_events",
    "citation_styles",
    "reference_render_cache",
    "document_projects",
    "document_anchors",
    "document_citation_decisions",
    "external_mappings",
]


def test_all_tables_created():
    lib = _temp_library()
    conn = open_and_migrate(lib)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {row[0] for row in rows}
        for expected in EXPECTED_TABLES:
            assert expected in tables, f"Table {expected!r} missing after migration"
    finally:
        conn.close()


def test_foreign_keys_enforced():
    lib = _temp_library()
    conn = open_and_migrate(lib)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO reference_creators (reference_id, creator_id, role, position) "
                "VALUES ('nonexistent-ref', 'nonexistent-creator', 'author', 1)"
            )
            conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# open_and_migrate convenience helper
# ---------------------------------------------------------------------------

def test_open_and_migrate_returns_usable_connection():
    lib = _temp_library()
    conn = open_and_migrate(lib)
    try:
        # Basic sanity: can insert and query schema_version
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
        assert len(rows) >= 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Atomicity regression: a failing migration must leave no partial tables
# ---------------------------------------------------------------------------

def _inject_bad_migration(version: int, sql: str) -> None:
    """Write a temporary .sql file into the migrations directory for testing.

    The file is cleaned up by the test itself.
    """
    from citalio.db.connection import _migrations_dir
    path = _migrations_dir() / f"{version:03d}_test_bad_migration.sql"
    path.write_text(sql, encoding="utf-8")
    return path


def test_failing_migration_is_atomic():
    """A migration that fails partway through must not leave any partial tables
    or a schema_version row in the database.

    This proves that apply_migrations() wraps each migration in a single
    explicit transaction rather than using executescript() (which auto-commits
    before failure).
    """
    from citalio.db.connection import _migrations_dir

    # SQL that creates one table successfully and then fails on an intentional
    # syntax error.  The second statement is deliberately broken.
    bad_sql = (
        "CREATE TABLE _test_partial_table (id INTEGER PRIMARY KEY);\n"
        "THIS IS NOT VALID SQL AND WILL FAIL;\n"
    )

    # Pick a version number high enough not to clash with real migrations.
    bad_version = 999
    bad_path = _migrations_dir() / f"{bad_version:03d}_test_bad_migration.sql"

    try:
        lib = _temp_library()
        conn = open_db(lib)
        try:
            # First apply the real migrations so the schema is set up.
            # We do this BEFORE writing the bad file so that the good migrations
            # are already recorded and only version 999 is attempted on the
            # second call.
            apply_migrations(conn)

            # Now inject the bad migration file and attempt to apply it.
            bad_path.write_text(bad_sql, encoding="utf-8")

            # The bad migration must raise RuntimeError.
            with pytest.raises(RuntimeError, match="999_test_bad_migration.sql"):
                apply_migrations(conn)

            # The partial table must NOT exist.
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "_test_partial_table" not in tables, (
                "_test_partial_table was created despite migration failure — "
                "the migration was not atomic!"
            )

            # No schema_version row must have been recorded for version 999.
            row = conn.execute(
                "SELECT version FROM schema_version WHERE version = ?", (bad_version,)
            ).fetchone()
            assert row is None, (
                "schema_version row was recorded for the failing migration — "
                "atomicity violation!"
            )
        finally:
            conn.close()
    finally:
        # Always remove the injected migration file.
        if bad_path.exists():
            bad_path.unlink()
