"""Tests for local Zotero sync staging."""

from __future__ import annotations

import json

from citalio.connectors import zotero
from citalio.connectors.zotero import _merge_metadata, sync_local_zotero
from citalio.db.connection import open_and_migrate


def test_zotero_local_sync_dry_run_does_not_publish(monkeypatch, tmp_path):
    library = tmp_path / "library"
    conn = open_and_migrate(library)
    conn.close()

    metadata = [
        {
            "id": "dryRunPaper",
            "type": "article-journal",
            "title": "Dry Run Sync Paper",
            "citation-key": "dryRunPaper",
            "zotero-item-key": "PARENT123",
        }
    ]
    notes = [
        {
            "zotero-note-key": "NOTE1234",
            "zotero-item-key": "PARENT123",
            "note-html": "<p>Dry run sync note text.</p>",
            "note-type": "note",
        }
    ]
    fetch_report = zotero.ZoteroFetchReport(
        metadata_count=1,
        notes_count=1,
        notes_with_parent=1,
    )

    def fake_snapshot(base_url: str, timeout: int):
        return metadata, notes, fetch_report

    monkeypatch.setattr(zotero, "_fetch_local_zotero_snapshot", fake_snapshot)

    report = sync_local_zotero(library, dry_run=True)
    conn = open_and_migrate(library)
    try:
        ref_count = conn.execute('SELECT COUNT(*) FROM "references"').fetchone()[0]
        note_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    finally:
        conn.close()

    assert report.published is False
    assert report.metadata_report.counts.new_records == 1
    assert report.notes_report.counts.imported_notes == 1
    assert ref_count == 0
    assert note_count == 0
    report_file = next((library / "sync_reports").glob("zotero_local_sync_*.json"))
    assert json.loads(report_file.read_text())["published"] is False


def test_zotero_local_sync_publishes_after_staging(monkeypatch, tmp_path):
    library = tmp_path / "library"
    conn = open_and_migrate(library)
    conn.close()

    metadata = [
        {
            "id": "publishedPaper",
            "type": "article-journal",
            "title": "Published Sync Paper",
            "citation-key": "publishedPaper",
            "zotero-item-key": "PARENT123",
        }
    ]
    notes = [
        {
            "zotero-note-key": "NOTE1234",
            "zotero-item-key": "PARENT123",
            "note-html": "<p>Published sync note text.</p>",
            "note-type": "note",
        }
    ]
    fetch_report = zotero.ZoteroFetchReport(
        metadata_count=1,
        notes_count=1,
        notes_with_parent=1,
    )

    def fake_snapshot(base_url: str, timeout: int):
        return metadata, notes, fetch_report

    monkeypatch.setattr(zotero, "_fetch_local_zotero_snapshot", fake_snapshot)

    report = sync_local_zotero(library)
    conn = open_and_migrate(library)
    try:
        ref_count = conn.execute('SELECT COUNT(*) FROM "references"').fetchone()[0]
        note_text = conn.execute(
            "SELECT text FROM notes WHERE id = ?",
            ("zotero-note-NOTE1234",),
        ).fetchone()["text"]
    finally:
        conn.close()

    assert report.published is True
    assert report.backup_path is not None
    assert ref_count == 1
    assert note_text == "Published sync note text."


def test_zotero_metadata_merge_matches_uri_ids_without_positional_fallback():
    native = [
        {
            "key": "REALKEY1",
            "data": {"itemType": "journalArticle", "citationKey": "realPaper"},
            "links": {"alternate": {"href": "https://www.zotero.org/users/1/items/REALKEY1"}},
        }
    ]
    csl = [
        {
            "id": "http://zotero.org/users/1/items/REALKEY1",
            "type": "article-journal",
            "title": "Real Paper",
        }
    ]

    merged, report = _merge_metadata(native, csl)

    assert merged[0]["zotero-item-key"] == "REALKEY1"
    assert report.positional_fallback_used == 0


def test_zotero_metadata_merge_skips_standalone_top_level_notes():
    native = [
        {
            "key": "NOTEKEY1",
            "data": {"itemType": "note"},
            "links": {"alternate": {"href": "https://www.zotero.org/users/1/items/NOTEKEY1"}},
        }
    ]
    csl = [
        {
            "id": "http://zotero.org/users/1/items/NOTEKEY1",
            "type": "document",
            "title": "Scratch note",
        }
    ]

    merged, report = _merge_metadata(native, csl)

    assert merged == []
    assert report.positional_fallback_used == 0
    assert "Skipped standalone top-level Zotero note NOTEKEY1" in report.warnings[0]
