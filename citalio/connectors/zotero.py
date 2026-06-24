"""Read-only local Zotero sync adapter.

The adapter talks to Zotero's local HTTP API only. It does not read Zotero's
SQLite database, write to Zotero, or copy attachment/PDF files.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from citalio.db.connection import get_library_root, open_and_migrate
from citalio.formats.zotero_csl import (
    MigrationReport,
    NotesMigrationReport,
    ZOTERO_ITEM_URI_RE,
    import_zotero_csl_json,
    import_zotero_notes_json,
)


PAGE_SIZE = 100


@dataclass
class ZoteroFetchReport:
    metadata_count: int = 0
    notes_count: int = 0
    notes_with_parent: int = 0
    standalone_notes: int = 0
    positional_fallback_used: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class ZoteroSyncReport:
    library_root: str
    mode: str
    started_at: str
    finished_at: str
    metadata_report: MigrationReport
    notes_report: NotesMigrationReport
    fetch_report: ZoteroFetchReport
    staged_metadata_file: str
    staged_notes_file: str
    backup_path: str | None = None
    published: bool = False
    report_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "library_root": self.library_root,
            "mode": self.mode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "metadata_report": self.metadata_report.as_dict(),
            "notes_report": self.notes_report.as_dict(),
            "fetch_report": {
                "metadata_count": self.fetch_report.metadata_count,
                "notes_count": self.fetch_report.notes_count,
                "notes_with_parent": self.fetch_report.notes_with_parent,
                "standalone_notes": self.fetch_report.standalone_notes,
                "positional_fallback_used": self.fetch_report.positional_fallback_used,
                "warnings": self.fetch_report.warnings,
            },
            "staged_metadata_file": self.staged_metadata_file,
            "staged_notes_file": self.staged_notes_file,
            "backup_path": self.backup_path,
            "published": self.published,
            "report_path": self.report_path,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_json(url: str, timeout: int) -> list[dict[str, Any]]:
    if _should_prefer_windows_curl(url):
        return _fetch_json_via_windows_curl(url, timeout)
    req = urllib.request.Request(url, headers={"Zotero-API-Version": "3"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        if "127.0.0.1:23119" not in url and "localhost:23119" not in url:
            raise
        return _fetch_json_via_windows_curl(url, timeout)


def _should_prefer_windows_curl(url: str) -> bool:
    if "127.0.0.1:23119" not in url and "localhost:23119" not in url:
        return False
    try:
        version = Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in version or "wsl" in version


def _fetch_json_via_windows_curl(url: str, timeout: int) -> list[dict[str, Any]]:
    """Fetch Windows-local Zotero API from WSL when Linux localhost cannot see it."""
    curl_cmd = [
        "curl.exe",
        "-sS",
        "--max-time",
        str(timeout),
        "-H",
        "Zotero-API-Version: 3",
        url,
    ]
    try:
        completed = subprocess.run(
            curl_cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
            check=False,
        )
    except FileNotFoundError:
        raise
    if completed.returncode != 0:
        raise RuntimeError(
            "Could not fetch Zotero local API through Windows curl.exe: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return json.loads(completed.stdout)


def _fetch_all_pages(
    base_url: str,
    endpoint: str,
    params: dict[str, str],
    timeout: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    start = 0
    while True:
        query = urllib.parse.urlencode(
            {**params, "limit": str(PAGE_SIZE), "start": str(start)}
        )
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}?{query}"
        page = _fetch_json(url, timeout)
        if not page:
            break
        items.extend(page)
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
        time.sleep(0.05)
    return items


def _native_key_maps(
    native_items: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, str | None]], dict[int, dict[str, str | None]]]:
    by_citation_key: dict[str, dict[str, str | None]] = {}
    by_index: dict[int, dict[str, str | None]] = {}
    for idx, item in enumerate(native_items):
        data = item.get("data") or {}
        links = item.get("links") or {}
        info = {
            "zotero_key": item.get("key"),
            "zotero_uri": (links.get("alternate") or {}).get("href"),
            "zotero_local_url": (links.get("self") or {}).get("href"),
            "item_type": data.get("itemType"),
        }
        by_index[idx] = info
        citation_key = data.get("citationKey")
        if citation_key:
            by_citation_key[str(citation_key)] = info
    return by_citation_key, by_index


def _merge_metadata(
    native_items: list[dict[str, Any]],
    csl_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], ZoteroFetchReport]:
    if len(native_items) != len(csl_items):
        raise RuntimeError(
            f"Zotero snapshot is incomplete: native item count {len(native_items)} "
            f"does not match CSL item count {len(csl_items)}."
        )

    by_citation_key, by_index = _native_key_maps(native_items)
    merged: list[dict[str, Any]] = []
    report = ZoteroFetchReport(metadata_count=len(csl_items))

    for idx, csl_item in enumerate(csl_items):
        raw_id = csl_item.get("id")
        citation_key = csl_item.get("citation-key") or ""
        info = by_citation_key.get(str(citation_key)) if citation_key else None
        if info is None and isinstance(raw_id, str):
            match = ZOTERO_ITEM_URI_RE.search(raw_id)
            if match:
                native_key = match.group(1)
                info = next(
                    (
                        native_info
                        for native_info in by_index.values()
                        if native_info.get("zotero_key") == native_key
                    ),
                    None,
                )
        if info is None:
            info = by_index.get(idx)
            report.positional_fallback_used += 1
            report.warnings.append(
                "Used positional Zotero key fallback for item "
                f"{idx} ({citation_key or raw_id or 'no citation key'})."
            )
        if not info or not info.get("zotero_key"):
            raise RuntimeError(
                f"Zotero snapshot is incomplete: missing Zotero item key for item {idx}."
            )
        if info.get("item_type") == "note":
            report.warnings.append(
                f"Skipped standalone top-level Zotero note {info['zotero_key']} from reference metadata."
            )
            continue

        out = dict(csl_item)
        out["zotero-item-key"] = info["zotero_key"]
        out["zotero-item-uri"] = info.get("zotero_uri")
        merged.append(out)

    return merged, report


def _transform_note(raw: dict[str, Any]) -> dict[str, Any]:
    data = raw.get("data") or {}
    links = raw.get("links") or {}
    return {
        "zotero-note-key": raw.get("key", ""),
        "zotero-item-key": data.get("parentItem"),
        "note-html": data.get("note", ""),
        "note-type": data.get("itemType", "note"),
        "tags": [t.get("tag") for t in data.get("tags", []) if isinstance(t, dict)],
        "date-added": data.get("dateAdded"),
        "date-modified": data.get("dateModified"),
        "zotero-note-uri": (links.get("alternate") or {}).get("href"),
        "zotero-note-local-url": (links.get("self") or {}).get("href"),
        "zotero-parent-local-url": (links.get("up") or {}).get("href"),
        "version": raw.get("version"),
    }


def _fetch_local_zotero_snapshot(
    base_url: str,
    timeout: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], ZoteroFetchReport]:
    try:
        native_items = _fetch_all_pages(
            base_url, "items/top", {"format": "json"}, timeout
        )
        csl_items = _fetch_all_pages(
            base_url, "items/top", {"format": "csljson"}, timeout
        )
        raw_notes = _fetch_all_pages(
            base_url, "items", {"format": "json", "itemType": "note"}, timeout
        )
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Could not reach Zotero local API. Open Zotero and ensure the local API is enabled."
        ) from exc

    metadata, report = _merge_metadata(native_items, csl_items)
    notes = [_transform_note(raw) for raw in raw_notes]
    metadata_keys = {
        str(item["zotero-item-key"]) for item in metadata if item.get("zotero-item-key")
    }
    parent_keys = {
        str(note["zotero-item-key"]) for note in notes if note.get("zotero-item-key")
    }
    missing_parent_keys = sorted(parent_keys - metadata_keys)
    if missing_parent_keys:
        sample = ", ".join(missing_parent_keys[:5])
        raise RuntimeError(
            "Zotero snapshot is incomplete: note parent keys are missing from top-level metadata "
            f"({sample})."
        )

    report.notes_count = len(notes)
    report.notes_with_parent = sum(1 for note in notes if note.get("zotero-item-key"))
    report.standalone_notes = len(notes) - report.notes_with_parent
    if report.standalone_notes:
        report.warnings.append(
            f"{report.standalone_notes} standalone Zotero note(s) will be skipped because they have no parent item."
        )
    return metadata, notes, report


def _backup_database(source: Path, backup_dir: Path, timestamp: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"citalio_before_zotero_sync_{timestamp}.db"
    src = sqlite3.connect(str(source))
    try:
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return backup_path


def _copy_database(source: Path, dest: Path) -> None:
    src = sqlite3.connect(str(source))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def sync_local_zotero(
    library: Path | None = None,
    *,
    base_url: str = "http://127.0.0.1:23119/api/users/0",
    dry_run: bool = False,
    timeout: int = 30,
    report_path: Path | None = None,
) -> ZoteroSyncReport:
    """Fetch a complete Zotero local snapshot and sync it into Citalio atomically."""
    started_at = _now_iso()
    timestamp = started_at.replace(":", "-").replace(".", "-")
    root = get_library_root(library)
    conn = open_and_migrate(library)
    conn.close()
    db_path = root / "citalio.db"

    metadata, notes, fetch_report = _fetch_local_zotero_snapshot(base_url, timeout)

    sync_dir = root / "sync_staging"
    sync_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = sync_dir / f"zotero_metadata_{timestamp}.json"
    notes_path = sync_dir / f"zotero_notes_{timestamp}.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    notes_path.write_text(
        json.dumps(notes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with TemporaryDirectory(prefix="citalio-zotero-sync-") as tmp:
        tmp_root = Path(tmp)
        tmp_db = tmp_root / "citalio.db"
        _copy_database(db_path, tmp_db)
        tmp_conn = open_and_migrate(tmp_root)
        try:
            metadata_report = import_zotero_csl_json(
                tmp_conn,
                metadata_path,
                tmp_root,
                merge_policy="overwrite",
                report_path=tmp_root / "metadata-report.json",
            )
            notes_report = import_zotero_notes_json(
                tmp_conn,
                notes_path,
                tmp_root,
                update_existing=True,
                report_path=tmp_root / "notes-report.json",
            )
        finally:
            tmp_conn.close()

        backup_path: Path | None = None
        published = False
        if not dry_run:
            backup_path = _backup_database(db_path, root / "backups", timestamp)
            _copy_database(tmp_db, db_path)
            published = True

    finished_at = _now_iso()
    final_report = ZoteroSyncReport(
        library_root=str(root),
        mode="dry-run" if dry_run else "write",
        started_at=started_at,
        finished_at=finished_at,
        metadata_report=metadata_report,
        notes_report=notes_report,
        fetch_report=fetch_report,
        staged_metadata_file=str(metadata_path),
        staged_notes_file=str(notes_path),
        backup_path=str(backup_path) if backup_path else None,
        published=published,
    )
    final_report_path = report_path or (
        root / "sync_reports" / f"zotero_local_sync_{timestamp}.json"
    )
    final_report_path.parent.mkdir(parents=True, exist_ok=True)
    final_report.report_path = str(final_report_path)
    final_report_path.write_text(
        json.dumps(final_report.as_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return final_report
