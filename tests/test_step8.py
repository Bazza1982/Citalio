"""Tests for Step 8 markdown citation insertion."""

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
from citalio.documents.markdown_insertion import InsertionResult, _format_marker, insert_citations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path):
    return open_and_migrate(tmp_path / ".citalio")


def _make_project(conn, name="test"):
    proj_repo = DocumentCitationRepository(conn)
    p = DocumentProjectRecord(name=name)
    proj_repo.create_project(p)
    return p


def _make_ref(conn, citekey="smith2020", title="Test Reference"):
    ref_repo = CitationRepository(conn)
    r = ReferenceRecord(title=title, citekey=citekey)
    ref_repo.create_reference(r)
    return r


def _make_anchor(conn, project_id, anchor_text="Institutions matter."):
    proj_repo = DocumentCitationRepository(conn)
    a = DocumentAnchorRecord(project_id=project_id, anchor_text=anchor_text)
    proj_repo.upsert_anchor(a)
    return a


def _make_decision(conn, project_id, ref_id, anchor_id, marker, state="approved"):
    proj_repo = DocumentCitationRepository(conn)
    d = DocumentCitationDecisionRecord(
        project_id=project_id,
        reference_id=ref_id,
        anchor_id=anchor_id,
        citation_marker=marker,
        decision_state=state,
    )
    proj_repo.record_decision(d)
    return d


# ---------------------------------------------------------------------------
# _format_marker
# ---------------------------------------------------------------------------

def test_format_marker_bare_key():
    assert _format_marker("smith2020") == "[@smith2020]"


def test_format_marker_at_prefix():
    assert _format_marker("@smith2020") == "[@smith2020]"


def test_format_marker_already_formatted():
    assert _format_marker("[@smith2020]") == "[@smith2020]"


def test_format_marker_bracket_no_at():
    assert _format_marker("[smith2020]") == "[@smith2020]"


# ---------------------------------------------------------------------------
# insert_citations
# ---------------------------------------------------------------------------

def test_insert_basic(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    r = _make_ref(conn)
    a = _make_anchor(conn, p.id, "Institutions matter.")
    _make_decision(conn, p.id, r.id, a.id, "smith2020")

    md = tmp_path / "draft.md"
    md.write_text("Some intro.\n\nInstitutions matter. More text.\n", encoding="utf-8")

    result = insert_citations(conn, p.id, md)

    assert result.inserted == 1
    assert result.already_present == 0
    content = md.read_text(encoding="utf-8")
    assert "[@smith2020]" in content
    # Marker placed right after anchor text.
    assert "Institutions matter.[@smith2020]" in content


def test_insert_idempotent(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    r = _make_ref(conn)
    a = _make_anchor(conn, p.id, "Institutions matter.")
    _make_decision(conn, p.id, r.id, a.id, "smith2020")

    md = tmp_path / "draft.md"
    md.write_text("Institutions matter. More text.\n", encoding="utf-8")

    # First run
    r1 = insert_citations(conn, p.id, md)
    assert r1.inserted == 1

    # Second run — decision is already 'inserted', so nothing to process.
    r2 = insert_citations(conn, p.id, md)
    assert r2.inserted == 0

    # Only one marker in the document
    content = md.read_text(encoding="utf-8")
    assert content.count("[@smith2020]") == 1


def test_insert_multiple_markers_same_anchor(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    r1 = _make_ref(conn, citekey="smith2020", title="Ref A")
    r2 = _make_ref(conn, citekey="jones2019", title="Ref B")
    a = _make_anchor(conn, p.id, "Institutions matter.")
    _make_decision(conn, p.id, r1.id, a.id, "smith2020")
    _make_decision(conn, p.id, r2.id, a.id, "jones2019")

    md = tmp_path / "draft.md"
    md.write_text("Institutions matter. More text.\n", encoding="utf-8")

    result = insert_citations(conn, p.id, md)
    assert result.inserted == 2

    content = md.read_text(encoding="utf-8")
    assert "[@smith2020]" in content
    assert "[@jones2019]" in content


def test_insert_anchor_not_in_document(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    r = _make_ref(conn)
    a = _make_anchor(conn, p.id, "This text is not in the doc.")
    _make_decision(conn, p.id, r.id, a.id, "smith2020")

    md = tmp_path / "draft.md"
    md.write_text("Completely different content.\n", encoding="utf-8")

    result = insert_citations(conn, p.id, md)
    assert result.inserted == 0
    assert result.anchor_not_found == 1


def test_insert_no_decisions(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)

    md = tmp_path / "draft.md"
    md.write_text("Some content.\n", encoding="utf-8")

    result = insert_citations(conn, p.id, md)
    assert result.inserted == 0


def test_insert_output_path(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    r = _make_ref(conn)
    a = _make_anchor(conn, p.id, "Institutions matter.")
    _make_decision(conn, p.id, r.id, a.id, "smith2020")

    md_in = tmp_path / "draft.md"
    md_out = tmp_path / "draft_cited.md"
    md_in.write_text("Institutions matter. More text.\n", encoding="utf-8")

    insert_citations(conn, p.id, md_in, output_path=md_out)

    # Source unchanged
    assert "[@smith2020]" not in md_in.read_text(encoding="utf-8")
    # Output has marker
    assert "[@smith2020]" in md_out.read_text(encoding="utf-8")


def test_insert_updates_decision_state(tmp_path):
    conn = _make_db(tmp_path)
    p = _make_project(conn)
    r = _make_ref(conn)
    a = _make_anchor(conn, p.id, "Institutions matter.")
    d = _make_decision(conn, p.id, r.id, a.id, "smith2020")

    md = tmp_path / "draft.md"
    md.write_text("Institutions matter. More text.\n", encoding="utf-8")

    insert_citations(conn, p.id, md)

    proj_repo = DocumentCitationRepository(conn)
    updated = proj_repo.get_decision(d.id)
    assert updated.decision_state == "inserted"
