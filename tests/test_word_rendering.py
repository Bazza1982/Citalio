"""Tests for Step 9: Word document citation rendering."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

docx = pytest.importorskip("docx", reason="python-docx not installed")
from docx import Document  # noqa: E402

from citalio.db.connection import open_and_migrate
from citalio.db.models import (
    DocumentAnchorRecord,
    DocumentCitationDecisionRecord,
    DocumentProjectRecord,
    ReferenceRecord,
)
from citalio.db.project_repository import DocumentCitationRepository
from citalio.db.repository import CitationRepository
from citalio.rendering.word import (
    RenderingResult,
    _format_bibliography_entry,
    _format_inline,
    render_docx,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "citalio.db"
    c = open_and_migrate(tmp_path)
    yield c
    c.close()


def _make_ref(conn, citekey: str, title: str, year: int = 2020, family: str = "Smith") -> str:
    from citalio.db.models import CreatorRecord

    ref_repo = CitationRepository(conn)
    ref = ReferenceRecord(citekey=citekey, title=title, year=year)
    ref_id = ref_repo.create_reference(ref)

    creator = CreatorRecord(family=family, given="J.")
    creator_id = ref_repo.get_or_create_creator(creator)
    ref_repo.link_creator_to_reference(ref_id, creator_id, "author", 0)
    return ref_id


def _make_project(conn, name="Test", docx_path: str | None = None) -> str:
    proj_repo = DocumentCitationRepository(conn)
    p = DocumentProjectRecord(name=name, docx_path=docx_path)
    return proj_repo.create_project(p)


def _make_decision(
    conn,
    project_id: str,
    ref_id: str,
    citekey: str,
    state: str = "inserted",
    anchor_id: str | None = None,
) -> str:
    proj_repo = DocumentCitationRepository(conn)
    d = DocumentCitationDecisionRecord(
        project_id=project_id,
        reference_id=ref_id,
        citation_marker=citekey,
        anchor_id=anchor_id,
        decision_state=state,
    )
    return proj_repo.record_decision(d)


def _make_docx(tmp_path: Path, paragraphs: list[str], filename: str = "test.docx") -> Path:
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    path = tmp_path / filename
    doc.save(path)
    return path


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

class _FakeCreator:
    def __init__(self, family, given=None, literal=None):
        self.family = family
        self.given = given
        self.literal = literal


class _FakeRef:
    def __init__(self, authors, year, title="A Title", doi=None, url=None,
                 publication_title=None, volume=None, issue=None, pages=None,
                 publisher=None):
        self.authors = authors
        self.year = year
        self.title = title
        self.doi = doi
        self.url = url
        self.publication_title = publication_title
        self.volume = volume
        self.issue = issue
        self.pages = pages
        self.publisher = publisher


def test_format_inline_single_author():
    ref = _FakeRef([_FakeCreator("Smith")], 2020)
    assert _format_inline(ref) == "(Smith, 2020)"


def test_format_inline_two_authors():
    ref = _FakeRef([_FakeCreator("Smith"), _FakeCreator("Jones")], 2021)
    assert _format_inline(ref) == "(Smith & Jones, 2021)"


def test_format_inline_et_al():
    ref = _FakeRef([_FakeCreator("A"), _FakeCreator("B"), _FakeCreator("C")], 2022)
    assert _format_inline(ref) == "(A et al., 2022)"


def test_format_inline_no_year():
    ref = _FakeRef([_FakeCreator("Smith")], None)
    assert _format_inline(ref) == "(Smith, n.d.)"


def test_format_inline_no_authors():
    ref = _FakeRef([], 2020)
    assert _format_inline(ref) == "(Unknown, 2020)"


def test_bibliography_entry_basic():
    ref = _FakeRef([_FakeCreator("Smith", "John")], 2020, title="My Paper")
    entry = _format_bibliography_entry(ref)
    assert "Smith, J." in entry
    assert "(2020)" in entry
    assert "My Paper" in entry


def test_bibliography_entry_journal():
    ref = _FakeRef(
        [_FakeCreator("Smith", "J.")],
        2020,
        title="My Paper",
        publication_title="Nature",
        volume="10",
        issue="2",
        pages="100-110",
    )
    entry = _format_bibliography_entry(ref)
    assert "Nature" in entry
    assert "10(2)" in entry
    assert "100-110" in entry


def test_bibliography_entry_doi():
    ref = _FakeRef([_FakeCreator("Smith")], 2020, title="T", doi="10.1234/test")
    entry = _format_bibliography_entry(ref)
    assert "https://doi.org/10.1234/test" in entry


def test_bibliography_entry_url_fallback():
    ref = _FakeRef([_FakeCreator("Smith")], 2020, title="T", url="https://example.com")
    entry = _format_bibliography_entry(ref)
    assert "https://example.com" in entry


# ---------------------------------------------------------------------------
# render_docx — core behaviour
# ---------------------------------------------------------------------------

def test_render_basic_marker_replacement(conn, tmp_path):
    ref_id = _make_ref(conn, "smith2020", "Test Paper", year=2020)
    proj_id = _make_project(conn)
    _make_decision(conn, proj_id, ref_id, "smith2020", state="inserted")

    docx_path = _make_docx(tmp_path, ["Institutions matter [@smith2020]."])
    out_path = tmp_path / "out.docx"

    result = render_docx(conn, proj_id, docx_path, output_path=out_path, _allow_experimental=True)

    assert result.markers_replaced == 1
    assert result.rendered_decisions == 1
    assert result.markers_not_in_doc == 0
    assert out_path.exists()

    rendered_doc = Document(out_path)
    text = "\n".join(p.text for p in rendered_doc.paragraphs)
    assert "(Smith, 2020)" in text
    assert "[@smith2020]" not in text


def test_render_multiple_markers(conn, tmp_path):
    ref1 = _make_ref(conn, "smith2020", "Paper A", year=2020, family="Smith")
    ref2 = _make_ref(conn, "jones2021", "Paper B", year=2021, family="Jones")
    proj_id = _make_project(conn)
    _make_decision(conn, proj_id, ref1, "smith2020", state="inserted")
    _make_decision(conn, proj_id, ref2, "jones2021", state="inserted")

    docx_path = _make_docx(tmp_path, [
        "First claim [@smith2020].",
        "Second claim [@jones2021].",
    ])
    out_path = tmp_path / "out.docx"

    result = render_docx(conn, proj_id, docx_path, output_path=out_path, _allow_experimental=True)

    assert result.markers_replaced == 2
    assert result.rendered_decisions == 2

    text = "\n".join(p.text for p in Document(out_path).paragraphs)
    assert "(Smith, 2020)" in text
    assert "(Jones, 2021)" in text


def test_render_approved_state_also_processed(conn, tmp_path):
    ref_id = _make_ref(conn, "smith2020", "T", year=2020)
    proj_id = _make_project(conn)
    _make_decision(conn, proj_id, ref_id, "smith2020", state="approved")

    docx_path = _make_docx(tmp_path, ["See [@smith2020] for details."])
    out_path = tmp_path / "out.docx"

    result = render_docx(conn, proj_id, docx_path, output_path=out_path, _allow_experimental=True)
    assert result.rendered_decisions == 1


def test_render_repaired_state_also_processed(conn, tmp_path):
    ref_id = _make_ref(conn, "smith2020", "T", year=2020)
    proj_id = _make_project(conn)
    _make_decision(conn, proj_id, ref_id, "smith2020", state="repaired")

    docx_path = _make_docx(tmp_path, ["[@smith2020]"])
    out_path = tmp_path / "out.docx"

    result = render_docx(conn, proj_id, docx_path, output_path=out_path, _allow_experimental=True)
    assert result.rendered_decisions == 1


def test_render_marker_not_in_document(conn, tmp_path):
    ref_id = _make_ref(conn, "smith2020", "T", year=2020)
    proj_id = _make_project(conn)
    _make_decision(conn, proj_id, ref_id, "smith2020", state="inserted")

    # Document doesn't have the marker
    docx_path = _make_docx(tmp_path, ["Plain text without any markers."])
    out_path = tmp_path / "out.docx"

    result = render_docx(conn, proj_id, docx_path, output_path=out_path, _allow_experimental=True)

    assert result.markers_replaced == 0
    assert result.rendered_decisions == 0
    assert result.markers_not_in_doc == 1


def test_render_no_decisions_copies_file(conn, tmp_path):
    proj_id = _make_project(conn)
    docx_path = _make_docx(tmp_path, ["No citations here."])
    out_path = tmp_path / "out.docx"

    result = render_docx(conn, proj_id, docx_path, output_path=out_path, _allow_experimental=True)

    assert result.rendered_decisions == 0
    assert result.markers_replaced == 0
    assert out_path.exists()


def test_render_decision_state_transition(conn, tmp_path):
    ref_id = _make_ref(conn, "smith2020", "T", year=2020)
    proj_id = _make_project(conn)
    did = _make_decision(conn, proj_id, ref_id, "smith2020", state="inserted")

    docx_path = _make_docx(tmp_path, ["[@smith2020]"])
    render_docx(conn, proj_id, docx_path, output_path=tmp_path / "out.docx", _allow_experimental=True)

    proj_repo = DocumentCitationRepository(conn)
    decision = proj_repo.get_decision(did)
    assert decision.decision_state == "rendered"


def test_render_bibliography_appended(conn, tmp_path):
    ref_id = _make_ref(conn, "smith2020", "My Great Paper", year=2020, family="Smith")
    proj_id = _make_project(conn)
    _make_decision(conn, proj_id, ref_id, "smith2020", state="inserted")

    docx_path = _make_docx(tmp_path, ["See [@smith2020]."])
    out_path = tmp_path / "out.docx"

    result = render_docx(conn, proj_id, docx_path, output_path=out_path, bibliography=True, _allow_experimental=True)

    assert result.bibliography_entries == 1
    text = "\n".join(p.text for p in Document(out_path).paragraphs)
    assert "References" in text
    assert "Smith" in text
    assert "My Great Paper" in text


def test_render_no_bibliography(conn, tmp_path):
    ref_id = _make_ref(conn, "smith2020", "T", year=2020)
    proj_id = _make_project(conn)
    _make_decision(conn, proj_id, ref_id, "smith2020", state="inserted")

    docx_path = _make_docx(tmp_path, ["[@smith2020]"])
    out_path = tmp_path / "out.docx"

    result = render_docx(conn, proj_id, docx_path, output_path=out_path, bibliography=False, _allow_experimental=True)

    assert result.bibliography_entries == 0
    text = "\n".join(p.text for p in Document(out_path).paragraphs)
    assert "References" not in text


def test_render_default_output_path(conn, tmp_path):
    proj_id = _make_project(conn)
    docx_path = _make_docx(tmp_path, ["No markers."])

    result = render_docx(conn, proj_id, docx_path, _allow_experimental=True)

    expected = tmp_path / "test_rendered.docx"
    assert expected.exists()


def test_render_bibliography_sorted_alphabetically(conn, tmp_path):
    ref1 = _make_ref(conn, "zeta2020", "Zeta Paper", year=2020, family="Zeta")
    ref2 = _make_ref(conn, "alpha2019", "Alpha Paper", year=2019, family="Alpha")
    proj_id = _make_project(conn)
    _make_decision(conn, proj_id, ref1, "zeta2020", state="inserted")
    _make_decision(conn, proj_id, ref2, "alpha2019", state="inserted")

    docx_path = _make_docx(tmp_path, ["[@zeta2020] and [@alpha2019]."])
    out_path = tmp_path / "out.docx"

    render_docx(conn, proj_id, docx_path, output_path=out_path, _allow_experimental=True)

    paragraphs = [p.text for p in Document(out_path).paragraphs if p.text.strip()]
    # Find "References" heading position
    ref_idx = next(i for i, t in enumerate(paragraphs) if t == "References")
    bib_entries = paragraphs[ref_idx + 1:]
    # Alpha should come before Zeta
    alpha_pos = next(i for i, t in enumerate(bib_entries) if "Alpha" in t)
    zeta_pos = next(i for i, t in enumerate(bib_entries) if "Zeta" in t)
    assert alpha_pos < zeta_pos


def test_render_markers_in_table_cells(conn, tmp_path):
    ref_id = _make_ref(conn, "smith2020", "T", year=2020)
    proj_id = _make_project(conn)
    _make_decision(conn, proj_id, ref_id, "smith2020", state="inserted")

    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Evidence"
    table.cell(0, 1).paragraphs[0].add_run("See [@smith2020].")
    docx_path = tmp_path / "table.docx"
    doc.save(docx_path)

    out_path = tmp_path / "out.docx"
    result = render_docx(conn, proj_id, docx_path, output_path=out_path, bibliography=False, _allow_experimental=True)

    assert result.markers_replaced == 1
    rendered_doc = Document(out_path)
    cell_text = rendered_doc.tables[0].cell(0, 1).text
    assert "(Smith, 2020)" in cell_text
    assert "[@smith2020]" not in cell_text


def test_render_decision_without_marker_skipped(conn, tmp_path):
    proj_id = _make_project(conn)
    proj_repo = DocumentCitationRepository(conn)
    # Decision with no citation_marker
    d = DocumentCitationDecisionRecord(
        project_id=proj_id,
        reference_id=None,
        citation_marker=None,
        decision_state="inserted",
    )
    proj_repo.record_decision(d)

    docx_path = _make_docx(tmp_path, ["Plain text."])
    out_path = tmp_path / "out.docx"

    result = render_docx(conn, proj_id, docx_path, output_path=out_path, _allow_experimental=True)
    assert result.markers_replaced == 0
    # The no-marker decision is tracked in details
    assert any(detail.get("status") == "no_marker" for detail in result.details)


def test_render_original_file_not_modified(conn, tmp_path):
    ref_id = _make_ref(conn, "smith2020", "T", year=2020)
    proj_id = _make_project(conn)
    _make_decision(conn, proj_id, ref_id, "smith2020", state="inserted")

    docx_path = _make_docx(tmp_path, ["[@smith2020]"])
    original_mtime = docx_path.stat().st_mtime

    out_path = tmp_path / "out.docx"
    render_docx(conn, proj_id, docx_path, output_path=out_path, _allow_experimental=True)

    # Original must not have been touched
    assert docx_path.stat().st_mtime == original_mtime
    original_text = "\n".join(p.text for p in Document(docx_path).paragraphs)
    assert "[@smith2020]" in original_text
