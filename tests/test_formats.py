"""Tests for CSL-JSON and BibTeX import/export round-trips."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citalio.db.connection import apply_migrations, open_db
from citalio.db.models import CreatorRecord, ReferenceRecord
from citalio.db.repository import CitationRepository
from citalio.formats.csl_json import export_csl_json, import_csl_json
from citalio.formats.bibtex import export_bibtex, import_bibtex


@pytest.fixture()
def conn(tmp_path):
    db_conn = open_db(tmp_path / "lib")
    apply_migrations(db_conn)
    yield db_conn
    db_conn.close()


@pytest.fixture()
def repo(conn):
    return CitationRepository(conn)


# ---------------------------------------------------------------------------
# CSL-JSON fixtures
# ---------------------------------------------------------------------------

CSL_FIXTURE = [
    {
        "id": "item1",
        "type": "article-journal",
        "title": "Attention Is All You Need",
        "DOI": "10.5555/3295222.3295349",
        "author": [
            {"family": "Vaswani", "given": "Ashish"},
            {"family": "Shazeer", "given": "Noam"},
        ],
        "issued": {"date-parts": [[2017]]},
        "container-title": "Advances in Neural Information Processing Systems",
        "volume": "30",
        "abstract": "The dominant sequence transduction models are based on complex neural networks.",
    },
    {
        "id": "item2",
        "type": "book",
        "title": "Deep Learning",
        "author": [
            {"family": "Goodfellow", "given": "Ian"},
            {"family": "Bengio", "given": "Yoshua"},
        ],
        "issued": {"date-parts": [[2016]]},
        "publisher": "MIT Press",
    },
]


# ---------------------------------------------------------------------------
# CSL-JSON round-trip
# ---------------------------------------------------------------------------

def test_csl_json_import_count(conn, tmp_path):
    f = tmp_path / "refs.json"
    f.write_text(json.dumps(CSL_FIXTURE), encoding="utf-8")
    count = import_csl_json(conn, f)
    assert count == 2


def test_csl_json_import_fields(conn, repo, tmp_path):
    f = tmp_path / "refs.json"
    f.write_text(json.dumps(CSL_FIXTURE), encoding="utf-8")
    import_csl_json(conn, f)

    ref = repo.find_by_doi("10.5555/3295222.3295349")
    assert ref is not None
    assert ref.title == "Attention Is All You Need"
    assert ref.year == 2017
    assert ref.publication_title == "Advances in Neural Information Processing Systems"
    assert len(ref.authors) == 2
    assert ref.authors[0].family == "Vaswani"


def test_csl_json_round_trip(conn, tmp_path):
    """Import then export — key fields must survive."""
    in_file = tmp_path / "in.json"
    out_file = tmp_path / "out.json"
    in_file.write_text(json.dumps(CSL_FIXTURE), encoding="utf-8")

    import_csl_json(conn, in_file)
    count = export_csl_json(conn, out_file)
    assert count == 2

    exported = json.loads(out_file.read_text(encoding="utf-8"))
    assert isinstance(exported, list)
    assert len(exported) == 2

    titles = {item["title"] for item in exported}
    assert "Attention Is All You Need" in titles
    assert "Deep Learning" in titles

    # DOI must survive
    dois = {item.get("DOI") for item in exported}
    assert "10.5555/3295222.3295349" in dois

    # Author must survive
    transformer = next(i for i in exported if i["title"] == "Attention Is All You Need")
    assert transformer["author"][0]["family"] == "Vaswani"


def test_csl_json_import_idempotent(conn, tmp_path):
    """Importing the same file twice should not duplicate records."""
    f = tmp_path / "refs.json"
    f.write_text(json.dumps(CSL_FIXTURE), encoding="utf-8")
    import_csl_json(conn, f)
    import_csl_json(conn, f)

    rows = conn.execute('SELECT COUNT(*) FROM "references"').fetchone()
    assert rows[0] == 2


# ---------------------------------------------------------------------------
# BibTeX fixtures
# ---------------------------------------------------------------------------

BIBTEX_FIXTURE = """\
@article{lecun1998gradient,
  title = {Gradient-based learning applied to document recognition},
  author = {LeCun, Yann and Bottou, Leon and Bengio, Yoshua and Haffner, Patrick},
  year = {1998},
  journal = {Proceedings of the IEEE},
  volume = {86},
  number = {11},
  pages = {2278--2324},
  doi = {10.1109/5.726791},
}

@book{bishop2006pattern,
  title = {Pattern Recognition and Machine Learning},
  author = {Bishop, Christopher M.},
  year = {2006},
  publisher = {Springer},
  address = {New York},
}
"""


# ---------------------------------------------------------------------------
# BibTeX round-trip
# ---------------------------------------------------------------------------

def test_bibtex_import_count(conn, tmp_path):
    f = tmp_path / "refs.bib"
    f.write_text(BIBTEX_FIXTURE, encoding="utf-8")
    count = import_bibtex(conn, f)
    assert count == 2


def test_bibtex_import_fields(conn, repo, tmp_path):
    f = tmp_path / "refs.bib"
    f.write_text(BIBTEX_FIXTURE, encoding="utf-8")
    import_bibtex(conn, f)

    ref = repo.find_by_citekey("lecun1998gradient")
    assert ref is not None
    assert "Gradient-based learning" in ref.title
    assert ref.year == 1998
    assert ref.volume == "86"
    assert ref.doi == "10.1109/5.726791"
    assert len(ref.authors) == 4
    assert ref.authors[0].family == "LeCun"


def test_bibtex_round_trip(conn, tmp_path):
    """Import then export — key fields must survive."""
    in_file = tmp_path / "in.bib"
    out_file = tmp_path / "out.bib"
    in_file.write_text(BIBTEX_FIXTURE, encoding="utf-8")

    import_bibtex(conn, in_file)
    count = export_bibtex(conn, out_file)
    assert count == 2

    out_text = out_file.read_text(encoding="utf-8")
    assert "Gradient-based learning" in out_text
    assert "Pattern Recognition" in out_text
    # Author should appear
    assert "LeCun" in out_text
    assert "Bishop" in out_text


def test_bibtex_import_idempotent(conn, tmp_path):
    """Importing the same .bib twice should not duplicate records."""
    f = tmp_path / "refs.bib"
    f.write_text(BIBTEX_FIXTURE, encoding="utf-8")
    import_bibtex(conn, f)
    import_bibtex(conn, f)

    rows = conn.execute('SELECT COUNT(*) FROM "references"').fetchone()
    assert rows[0] == 2


# ---------------------------------------------------------------------------
# CSL-JSON error handling
# ---------------------------------------------------------------------------

def test_csl_json_invalid_top_level_raises(conn, tmp_path):
    """CSL-JSON file that is not an array must raise ValueError."""
    f = tmp_path / "bad.json"
    f.write_text('{"type": "article", "title": "Lone object"}', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        import_csl_json(conn, f)


def test_csl_json_empty_array(conn, tmp_path):
    """Importing an empty CSL-JSON array should succeed and return 0."""
    f = tmp_path / "empty.json"
    f.write_text("[]", encoding="utf-8")
    count = import_csl_json(conn, f)
    assert count == 0


def test_csl_json_skips_malformed_items(conn, tmp_path):
    """A malformed item (e.g. missing title key causing downstream error) must be
    skipped without aborting the whole import — the valid item must land in DB."""
    items = [
        # Valid item
        {"id": "good", "type": "article-journal", "title": "Valid Paper",
         "DOI": "10.9999/valid.001",
         "author": [{"family": "Good", "given": "Author"}],
         "issued": {"date-parts": [[2022]]}},
        # Invalid item: type is intentionally a non-string to trigger an error
        # during record construction in a controlled way.  We force the error by
        # passing a dict as the "title" value which Pydantic will reject.
        {"id": "bad", "type": "article-journal", "title": {"nested": "bad"},
         "issued": {"date-parts": [[2022]]}},
    ]
    f = tmp_path / "mixed.json"
    import json as _json
    f.write_text(_json.dumps(items), encoding="utf-8")

    import warnings
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        count = import_csl_json(conn, f)

    # Exactly 1 valid item imported, 1 skipped with a warning
    assert count == 1
    assert any("Skipping" in str(w.message) for w in caught)

    ref = repo_from_conn(conn).find_by_doi("10.9999/valid.001")
    assert ref is not None
    assert ref.title == "Valid Paper"


def test_csl_json_doi_preserved_exactly(conn, tmp_path):
    """DOI must survive import+export without modification."""
    doi = "10.1016/j.jml.2010.06.001"
    items = [{"type": "article-journal", "title": "Fidelity Test", "DOI": doi,
              "issued": {"date-parts": [[2010]]}}]
    f = tmp_path / "doi.json"
    import json as _json
    f.write_text(_json.dumps(items), encoding="utf-8")
    import_csl_json(conn, f)

    ref = repo_from_conn(conn).find_by_doi(doi)
    assert ref is not None
    assert ref.doi == doi


def test_csl_json_doi_stripped_on_import(conn, tmp_path):
    """DOI with surrounding whitespace in CSL-JSON must be stripped on import."""
    doi_clean = "10.9999/spaces.001"
    items = [{"type": "article-journal", "title": "Whitespace DOI",
              "DOI": f"  {doi_clean}  ",
              "issued": {"date-parts": [[2021]]}}]
    f = tmp_path / "space_doi.json"
    import json as _json
    f.write_text(_json.dumps(items), encoding="utf-8")
    import_csl_json(conn, f)

    ref = repo_from_conn(conn).find_by_doi(doi_clean)
    assert ref is not None, "Stripped DOI must be findable"
    assert ref.doi == doi_clean


def test_csl_json_year_raw_fallback(conn, tmp_path):
    """Year must be extracted from issued.raw when date-parts is absent."""
    items = [{"type": "article-journal", "title": "Raw Year Paper",
              "issued": {"raw": "2019-07-15"}}]
    f = tmp_path / "raw_year.json"
    import json as _json
    f.write_text(_json.dumps(items), encoding="utf-8")
    import_csl_json(conn, f)

    repo = repo_from_conn(conn)
    results = repo.search_references("Raw Year Paper")
    assert len(results) == 1
    assert results[0].year == 2019


# ---------------------------------------------------------------------------
# BibTeX error handling and fidelity
# ---------------------------------------------------------------------------

def test_bibtex_empty_file(conn, tmp_path):
    """Importing an empty .bib file should return 0 without error."""
    f = tmp_path / "empty.bib"
    f.write_text("", encoding="utf-8")
    count = import_bibtex(conn, f)
    assert count == 0


def test_bibtex_creator_order_preserved(conn, tmp_path):
    """Author order must be identical after BibTeX import round-trip."""
    bib = """\
@article{order2024,
  title = {Author Order Test},
  author = {Zeta, Alice and Mu, Bob and Alpha, Carol},
  year = {2024},
  journal = {Test Journal},
}
"""
    f = tmp_path / "order.bib"
    f.write_text(bib, encoding="utf-8")
    import_bibtex(conn, f)

    repo = repo_from_conn(conn)
    ref = repo.find_by_citekey("order2024")
    assert ref is not None
    families = [a.family for a in ref.authors]
    assert families == ["Zeta", "Mu", "Alpha"], f"Author order wrong: {families}"


def test_bibtex_year_fidelity(conn, tmp_path):
    """Year must be preserved exactly as an integer after BibTeX import."""
    bib = """\
@book{year2005,
  title = {Year Fidelity Book},
  author = {Smith, John},
  year = {2005},
  publisher = {Test Press},
}
"""
    f = tmp_path / "year.bib"
    f.write_text(bib, encoding="utf-8")
    import_bibtex(conn, f)

    ref = repo_from_conn(conn).find_by_citekey("year2005")
    assert ref is not None
    assert ref.year == 2005


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def repo_from_conn(conn):
    return CitationRepository(conn)
