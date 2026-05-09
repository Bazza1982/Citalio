"""Tests for Step 10 citation validation."""

from __future__ import annotations

import pytest

from citalio.db.connection import open_and_migrate
from citalio.db.models import (
    DocumentAnchorRecord,
    DocumentCitationDecisionRecord,
    DocumentProjectRecord,
    ReferenceRecord,
)
from citalio.db.project_repository import DocumentCitationRepository
from citalio.db.repository import CitationRepository
from citalio.documents.markdown_insertion import insert_citations
from citalio.validation.citation_validator import validate_project
from citalio.validation.reports import ValidationReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path):
    return open_and_migrate(tmp_path / ".citalio")


def _make_project(conn, name="test"):
    repo = DocumentCitationRepository(conn)
    p = DocumentProjectRecord(name=name)
    repo.create_project(p)
    return p


def _make_ref(conn, citekey="smith2020", title="Test Reference"):
    repo = CitationRepository(conn)
    r = ReferenceRecord(title=title, citekey=citekey)
    repo.create_reference(r)
    return r


def _make_anchor(conn, project_id, anchor_text="Institutions matter."):
    repo = DocumentCitationRepository(conn)
    a = DocumentAnchorRecord(project_id=project_id, anchor_text=anchor_text)
    repo.upsert_anchor(a)
    return a


def _make_decision(conn, project_id, ref_id, anchor_id, marker, state="approved"):
    repo = DocumentCitationRepository(conn)
    d = DocumentCitationDecisionRecord(
        project_id=project_id,
        reference_id=ref_id,
        anchor_id=anchor_id,
        citation_marker=marker,
        decision_state=state,
    )
    repo.record_decision(d)
    return d


# ---------------------------------------------------------------------------
# ValidationReport helpers
# ---------------------------------------------------------------------------

def test_report_is_valid_when_no_issues(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    report = validate_project(conn, p.id)
    assert report.is_valid
    assert "passed" in report.summary()


def test_report_write_json(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    report = validate_project(conn, p.id)
    out = tmp_path / "report.json"
    report.write_json(out)
    import json
    data = json.loads(out.read_text())
    assert data["project_id"] == p.id
    assert data["is_valid"] is True


# ---------------------------------------------------------------------------
# approved_not_inserted check
# ---------------------------------------------------------------------------

def test_approved_not_inserted_issue(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    r = _make_ref(conn)
    a = _make_anchor(conn, p.id)
    _make_decision(conn, p.id, r.id, a.id, "smith2020", state="approved")

    report = validate_project(conn, p.id)
    assert not report.is_valid
    types = [i.issue_type for i in report.issues]
    assert "approved_not_inserted" in types


def test_inserted_decision_no_issue(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    r = _make_ref(conn)
    a = _make_anchor(conn, p.id, "Institutions matter.")

    md = tmp_path / "draft.md"
    md.write_text("Institutions matter. More text.\n", encoding="utf-8")

    d = _make_decision(conn, p.id, r.id, a.id, "smith2020", state="approved")

    insert_citations(conn, p.id, md)

    report = validate_project(conn, p.id)
    assert report.is_valid, report.issues


# ---------------------------------------------------------------------------
# rejected_marker_in_document check
# ---------------------------------------------------------------------------

def test_rejected_marker_in_document(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    r = _make_ref(conn, citekey="smith2020")
    a = _make_anchor(conn, p.id, "Institutions matter.")
    _make_decision(conn, p.id, r.id, a.id, "smith2020", state="rejected")

    md = tmp_path / "draft.md"
    md.write_text("Institutions matter.[@smith2020] More text.\n", encoding="utf-8")

    report = validate_project(conn, p.id, markdown_path=md)
    types = [i.issue_type for i in report.issues]
    assert "rejected_marker_in_document" in types


# ---------------------------------------------------------------------------
# unresolved_marker check
# ---------------------------------------------------------------------------

def test_unresolved_marker_in_document(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)

    md = tmp_path / "draft.md"
    md.write_text("Some claim.[@ghost2099] More text.\n", encoding="utf-8")

    report = validate_project(conn, p.id, markdown_path=md)
    types = [i.issue_type for i in report.issues]
    assert "unresolved_marker" in types
    markers = [i.marker for i in report.issues]
    assert "ghost2099" in markers


def test_resolved_marker_no_issue(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    _make_ref(conn, citekey="smith2020")

    md = tmp_path / "draft.md"
    md.write_text("Some claim.[@smith2020] More text.\n", encoding="utf-8")

    report = validate_project(conn, p.id, markdown_path=md)
    unresolved = [i for i in report.issues if i.issue_type == "unresolved_marker"]
    assert len(unresolved) == 0


def test_compound_marker_resolved(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    _make_ref(conn, citekey="smith2020", title="A")
    _make_ref(conn, citekey="jones2019", title="B")

    md = tmp_path / "draft.md"
    md.write_text("Institutional theory.[@smith2020; @jones2019]\n", encoding="utf-8")

    report = validate_project(conn, p.id, markdown_path=md)
    unresolved = [i for i in report.issues if i.issue_type == "unresolved_marker"]
    assert len(unresolved) == 0


def test_no_markdown_skips_marker_checks(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)

    # Would be unresolved if markdown was provided, but it isn't.
    report = validate_project(conn, p.id, markdown_path=None)
    assert report.is_valid


# ---------------------------------------------------------------------------
# End-to-end: insert then validate
# ---------------------------------------------------------------------------

def test_insert_then_validate_passes(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    r = _make_ref(conn, citekey="smith2020")
    a = _make_anchor(conn, p.id, "Institutions shape behaviour.")
    _make_decision(conn, p.id, r.id, a.id, "smith2020", state="approved")

    md = tmp_path / "thesis.md"
    md.write_text("Chapter 1.\n\nInstitutions shape behaviour. Further discussion.\n", encoding="utf-8")

    insert_citations(conn, p.id, md)
    report = validate_project(conn, p.id, markdown_path=md)
    assert report.is_valid, report.issues
