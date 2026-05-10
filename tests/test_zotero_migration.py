"""Tests for safe Zotero CSL-JSON metadata migration."""

from __future__ import annotations

import json

from citalio.db.connection import apply_migrations, open_db
from citalio.db.models import CreatorRecord, ReferenceRecord
from citalio.db.repository import CitationRepository
from citalio.formats.zotero_csl import (
    import_zotero_csl_json,
    normalize_doi,
    normalize_title_for_match,
    zotero_external_mappings,
)


def _conn(tmp_path):
    conn = open_db(tmp_path / "lib")
    apply_migrations(conn)
    return conn


def _write_json(tmp_path, items):
    path = tmp_path / "zotero.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


def test_zotero_dry_run_writes_no_reference_rows(tmp_path):
    conn = _conn(tmp_path)
    path = _write_json(
        tmp_path,
        [
            {
                "id": "ZOT1",
                "type": "article-journal",
                "title": "Dry Run Paper",
                "DOI": "10.1000/dry-run",
                "author": [{"family": "Smith", "given": "Ada"}],
                "issued": {"date-parts": [[2024]]},
            }
        ],
    )

    report = import_zotero_csl_json(conn, path, tmp_path / "lib", dry_run=True)

    assert report.mode == "dry-run"
    assert report.counts.source_records == 1
    assert report.counts.new_records == 1
    assert conn.execute('SELECT COUNT(*) FROM "references"').fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM creators").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM provenance_events").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM external_mappings").fetchone()[0] == 0
    conn.close()


def test_zotero_write_imports_metadata_provenance_and_mapping(tmp_path):
    conn = _conn(tmp_path)
    path = _write_json(
        tmp_path,
        [
            {
                "id": "ABCD1234",
                "type": "article-journal",
                "title": "A Zotero Paper",
                "DOI": " https://doi.org/10.1016/example.001 ",
                "author": [{"family": "Chen", "given": "Li"}],
                "issued": {"date-parts": [[2021]]},
                "container-title": "Journal of Tests",
            }
        ],
    )

    report = import_zotero_csl_json(conn, path, tmp_path / "lib")
    repo = CitationRepository(conn)
    ref = repo.find_by_doi("10.1016/example.001")

    assert report.mode == "write"
    assert report.counts.new_records == 1
    assert report.counts.external_mappings_written == 1
    assert ref is not None
    assert ref.title == "A Zotero Paper"
    assert ref.year == 2021
    assert ref.publication_title == "Journal of Tests"
    assert ref.authors[0].family == "Chen"
    assert json.loads(ref.metadata_json)["raw_doi"] == " https://doi.org/10.1016/example.001 "

    provenance = conn.execute(
        "SELECT * FROM provenance_events WHERE reference_id = ?", (ref.id,)
    ).fetchone()
    assert provenance["source"] == "zotero-csl-json"
    assert provenance["source_record_id"] == "ABCD1234"
    assert provenance["before_json"] is None
    assert json.loads(provenance["after_json"])["id"] == "ABCD1234"

    mapping = conn.execute(
        "SELECT * FROM external_mappings WHERE connector = 'zotero-citation-key'"
    ).fetchone()
    assert mapping["reference_id"] == ref.id
    assert mapping["external_id"] == "ABCD1234"
    conn.close()


def test_zotero_identity_mappings_separate_citation_key_from_item_key():
    item = {
        "id": "smithImportantPaper",
        "citation-key": "smithImportantPaper",
        "zotero-item-key": "A1B2C3D4",
    }

    mappings = zotero_external_mappings(item)

    assert {
        "connector": "zotero-citation-key",
        "external_id": "smithImportantPaper",
        "external_url": None,
    } in mappings
    assert {
        "connector": "zotero-item-key",
        "external_id": "A1B2C3D4",
        "external_url": None,
    } in mappings


def test_zotero_identity_mapping_parses_item_uri():
    uri = "http://zotero.org/users/20221000/items/XYZ987AB"

    mappings = zotero_external_mappings({"id": uri})

    assert mappings == [
        {
            "connector": "zotero-item-key",
            "external_id": "XYZ987AB",
            "external_url": uri,
        }
    ]


def test_zotero_duplicate_doi_merges(tmp_path):
    conn = _conn(tmp_path)
    path = _write_json(
        tmp_path,
        [
            {
                "id": "ONE",
                "type": "article-journal",
                "title": "Original",
                "DOI": "10.1000/dupe",
                "author": [{"family": "First"}],
                "issued": {"date-parts": [[2020]]},
            },
            {
                "id": "TWO",
                "type": "article-journal",
                "title": "Changed",
                "DOI": "https://doi.org/10.1000/dupe",
                "author": [{"family": "Second"}],
                "issued": {"date-parts": [[2020]]},
            },
        ],
    )

    report = import_zotero_csl_json(conn, path, tmp_path / "lib")

    assert report.counts.new_records == 1
    assert report.counts.merged_records == 1
    assert report.counts.merged_by_doi == 1
    assert conn.execute('SELECT COUNT(*) FROM "references"').fetchone()[0] == 1
    conn.close()


def test_zotero_title_normalization_for_duplicate_report(tmp_path):
    conn = _conn(tmp_path)
    repo = CitationRepository(conn)
    repo.create_reference(
        ReferenceRecord(
            title="Institutional Theory",
            year=1995,
            authors=[CreatorRecord(family="Existing")],
        )
    )
    path = _write_json(
        tmp_path,
        [
            {
                "id": "TITLE1",
                "type": "article-journal",
                "title": " institutional theory. ",
                "author": [{"family": "Incoming"}],
                "issued": {"date-parts": [[1995]]},
            }
        ],
    )

    report = import_zotero_csl_json(conn, path, tmp_path / "lib")

    assert report.counts.merged_records == 1
    assert report.counts.merged_by_title_year_exact == 1
    assert conn.execute('SELECT COUNT(*) FROM "references"').fetchone()[0] == 1
    conn.close()


def test_zotero_attachment_fields_are_ignored_with_warning(tmp_path):
    conn = _conn(tmp_path)
    path = _write_json(
        tmp_path,
        [
            {
                "id": "ATTACH1",
                "type": "article-journal",
                "title": "Attachment Export",
                "DOI": "10.1000/attachment",
                "author": [{"family": "File"}],
                "attachment": "/do/not/copy.pdf",
            }
        ],
    )

    report = import_zotero_csl_json(conn, path, tmp_path / "lib")

    assert report.counts.attachment_fields_ignored == 1
    assert any(w.code == "attachment_fields_ignored" for w in report.warnings)
    assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    conn.close()


def test_zotero_organization_creator_maps_to_literal_author(tmp_path):
    conn = _conn(tmp_path)
    path = _write_json(
        tmp_path,
        [
            {
                "id": "ORG1",
                "type": "report",
                "title": "Government Report",
                "author": [{"literal": "World Health Organization"}],
                "issued": {"date-parts": [[2022]]},
            }
        ],
    )

    report = import_zotero_csl_json(conn, path, tmp_path / "lib")
    ref = CitationRepository(conn).search_references("Government Report")[0]

    assert report.counts.organization_creators == 1
    assert ref.authors[0].literal == "World Health Organization"
    conn.close()


def test_zotero_large_export_warning(tmp_path):
    conn = _conn(tmp_path)
    path = _write_json(
        tmp_path,
        [{"id": f"R{i}", "type": "article-journal", "title": f"Paper {i}"} for i in range(3)],
    )

    report = import_zotero_csl_json(
        conn, path, tmp_path / "lib", dry_run=True, large_export_threshold=2
    )

    assert any(w.code == "large_export" for w in report.warnings)
    conn.close()


def test_zotero_report_file_is_written(tmp_path):
    conn = _conn(tmp_path)
    path = _write_json(tmp_path, [{"id": "R1", "type": "article", "title": "Report"}])
    report_path = tmp_path / "report.json"

    report = import_zotero_csl_json(
        conn, path, tmp_path / "lib", dry_run=True, report_path=report_path
    )

    assert report.report_path == str(report_path)
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["counts"]["source_records"] == 1
    assert written["mode"] == "dry-run"
    conn.close()


def test_zotero_normalizers_are_conservative():
    assert normalize_doi("doi:10.xxxx/abc")[0] == "10.xxxx/abc"
    assert normalize_doi("https://doi.org/10.1002/(SICI)1097-0266(199802)19:2<93::AID-SMJ932>3.0.CO;2-M")[0].startswith("10.1002/")
    assert normalize_title_for_match(" Institutional Theory. ") == "institutional theory"
