"""SQLite connection management and migration runner for Citalio."""

from __future__ import annotations

import importlib.resources
import sqlite3
from pathlib import Path


_DEFAULT_LIBRARY_ROOT = Path.home() / ".citalio"
_DB_NAME = "citalio.db"


def get_library_root(library: Path | None = None) -> Path:
    """Return the active library root, honouring CITALIO_HOME env var."""
    import os

    if library is not None:
        return library
    env = os.environ.get("CITALIO_HOME")
    if env:
        return Path(env)
    return _DEFAULT_LIBRARY_ROOT


def open_db(library: Path | None = None) -> sqlite3.Connection:
    """Open (or create) the Citalio SQLite database with required PRAGMAs.

    The connection uses WAL journal mode, a 5-second busy timeout, and
    enforces foreign key constraints.  Rows are returned as sqlite3.Row so
    callers can access columns by name.
    """
    root = get_library_root(library)
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / _DB_NAME

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")

    return conn


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

def _migrations_dir() -> Path:
    """Return the path to the bundled SQL migration files."""
    return Path(__file__).parent / "migrations"


def _list_migration_files() -> list[Path]:
    """Return migration .sql files sorted by their numeric prefix."""
    mdir = _migrations_dir()
    files = sorted(mdir.glob("*.sql"), key=lambda p: p.name)
    return files


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    """Return the set of already-applied migration version numbers."""
    try:
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
        return {row[0] for row in rows}
    except sqlite3.OperationalError:
        # schema_version table does not exist yet — fresh DB
        return set()


def _version_from_filename(path: Path) -> int:
    """Extract the version integer from a filename like '001_initial_schema.sql'."""
    stem = path.stem  # e.g. "001_initial_schema"
    prefix = stem.split("_")[0]
    return int(prefix)


def apply_migrations(conn: sqlite3.Connection) -> list[int]:
    """Apply any pending migrations in order.

    Each migration runs inside an explicit BEGIN/COMMIT transaction so that
    either all DDL in a migration is committed or none of it is — partial
    schema application cannot occur.  If a migration fails the transaction is
    rolled back and a RuntimeError is raised.

    Returns the list of version numbers that were applied this call.
    """
    applied = _applied_versions(conn)
    files = _list_migration_files()
    newly_applied: list[int] = []

    for path in files:
        version = _version_from_filename(path)
        if version in applied:
            continue

        sql = path.read_text(encoding="utf-8")
        try:
            # Use an explicit savepoint-style transaction.
            # isolation_level=None (autocommit) connections need explicit BEGIN;
            # for connections in the default deferred mode we issue BEGIN EXCLUSIVE
            # to acquire a write lock for the full migration before any DDL runs.
            conn.execute("BEGIN EXCLUSIVE")
            # Execute each statement individually so we stay inside our transaction.
            # sqlite3.executescript() issues its own implicit COMMIT first, which
            # would allow partial DDL to persist on failure — we avoid it here.
            statements = [s.strip() for s in sql.split(";") if s.strip()]
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at, description) VALUES (?, datetime('now'), ?)",
                (version, path.stem),
            )
            conn.execute("COMMIT")
            newly_applied.append(version)
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise RuntimeError(
                f"Migration {path.name} failed — database left in previous state."
            ) from exc

    return newly_applied


def open_and_migrate(library: Path | None = None) -> sqlite3.Connection:
    """Convenience: open DB, apply pending migrations, return connection."""
    conn = open_db(library)
    apply_migrations(conn)
    return conn
