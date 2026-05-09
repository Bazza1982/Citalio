"""Tests for CitationRepository."""

from __future__ import annotations

import sqlite3

import pytest

from citalio.db.connection import apply_migrations, open_db
from citalio.db.models import CreatorRecord, NoteRecord, ProvenanceEvent, ReferenceRecord
from citalio.db.repository import CitationRepository


@pytest.fixture()
def conn(tmp_path):
    """In-memory database with schema applied."""
    import os
    os.environ["CITALIO_HOME"] = str(tmp_path / "lib")
    db_conn = open_db(tmp_path / "lib")
    apply_migrations(db_conn)
    yield db_conn
    db_conn.close()


@pytest.fixture()
def repo(conn):
    return CitationRepository(conn)


@pytest.fixture()
def sample_ref():
    return ReferenceRecord(
        title="Deep Learning for Natural Language Processing",
        item_type="article-journal",
        year=2020,
        doi="10.1234/dlnlp.2020.001",
        citekey="smith2020deep",
        publication_title="Journal of AI Research",
        authors=[
            CreatorRecord(family="Smith", given="Alice"),
            CreatorRecord(family="Jones", given="Bob"),
        ],
    )


# ---------------------------------------------------------------------------
# create and get
# ---------------------------------------------------------------------------

def test_create_and_get_reference(repo, sample_ref):
    ref_id = repo.create_reference(sample_ref)
    assert ref_id == sample_ref.id

    fetched = repo.get_reference(ref_id)
    assert fetched is not None
    assert fetched.title == sample_ref.title
    assert fetched.year == 2020
    assert fetched.doi == "10.1234/dlnlp.2020.001"
    assert fetched.citekey == "smith2020deep"


def test_get_reference_not_found(repo):
    result = repo.get_reference("00000000-0000-0000-0000-000000000000")
    assert result is None


def test_create_reference_populates_authors(repo, sample_ref):
    repo.create_reference(sample_ref)
    fetched = repo.get_reference(sample_ref.id)
    assert len(fetched.authors) == 2
    assert fetched.authors[0].family == "Smith"
    assert fetched.authors[1].family == "Jones"


# ---------------------------------------------------------------------------
# find_by_doi
# ---------------------------------------------------------------------------

def test_find_by_doi(repo, sample_ref):
    repo.create_reference(sample_ref)
    found = repo.find_by_doi("10.1234/dlnlp.2020.001")
    assert found is not None
    assert found.id == sample_ref.id


def test_find_by_doi_not_found(repo):
    result = repo.find_by_doi("10.9999/doesnotexist")
    assert result is None


# ---------------------------------------------------------------------------
# find_by_citekey
# ---------------------------------------------------------------------------

def test_find_by_citekey(repo, sample_ref):
    repo.create_reference(sample_ref)
    found = repo.find_by_citekey("smith2020deep")
    assert found is not None
    assert found.id == sample_ref.id


def test_find_by_citekey_not_found(repo):
    result = repo.find_by_citekey("nobody1900nothing")
    assert result is None


# ---------------------------------------------------------------------------
# search_references
# ---------------------------------------------------------------------------

def test_search_references_by_title(repo, sample_ref):
    repo.create_reference(sample_ref)
    results = repo.search_references("Natural Language")
    assert any(r.id == sample_ref.id for r in results)


def test_search_references_by_citekey(repo, sample_ref):
    repo.create_reference(sample_ref)
    results = repo.search_references("smith2020")
    assert any(r.id == sample_ref.id for r in results)


def test_search_references_no_match(repo, sample_ref):
    repo.create_reference(sample_ref)
    results = repo.search_references("xyzzy_no_match_12345")
    assert results == []


def test_search_references_limit(repo):
    for i in range(10):
        repo.create_reference(ReferenceRecord(title=f"Paper {i} about climate change"))
    results = repo.search_references("climate change", limit=3)
    assert len(results) <= 3


# ---------------------------------------------------------------------------
# upsert_reference
# ---------------------------------------------------------------------------

def test_upsert_creates_when_missing(repo, sample_ref):
    ref_id = repo.upsert_reference(sample_ref)
    fetched = repo.get_reference(ref_id)
    assert fetched is not None
    assert fetched.doi == sample_ref.doi


def test_upsert_updates_when_doi_matches(repo, sample_ref):
    repo.create_reference(sample_ref)

    updated = sample_ref.model_copy(update={"abstract": "A great paper about NLP."})
    ref_id2 = repo.upsert_reference(updated)

    assert ref_id2 == sample_ref.id  # same record
    fetched = repo.get_reference(sample_ref.id)
    assert fetched.abstract == "A great paper about NLP."


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

def test_record_provenance(repo, conn, sample_ref):
    repo.create_reference(sample_ref)
    event = ProvenanceEvent(
        reference_id=sample_ref.id,
        event_type="import",
        source="test",
        message="Unit test import",
    )
    event_id = repo.record_provenance(event)
    row = conn.execute(
        "SELECT * FROM provenance_events WHERE id = ?", (event_id,)
    ).fetchone()
    assert row is not None
    assert row["event_type"] == "import"
    assert row["message"] == "Unit test import"


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------

def test_add_note(repo, conn, sample_ref):
    repo.create_reference(sample_ref)
    note = NoteRecord(reference_id=sample_ref.id, text="Very relevant to chapter 3.", source="user")
    note_id = repo.add_note(sample_ref.id, note)
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    assert row is not None
    assert row["text"] == "Very relevant to chapter 3."


# ---------------------------------------------------------------------------
# upsert_reference — creator merging regression tests
# ---------------------------------------------------------------------------

def test_upsert_adds_authors_on_second_upsert(repo):
    """Upsert with no authors first, then upsert again with authors.

    After the second upsert the reference must have the correct author count —
    the previous empty creator list must not shadow the new one.
    """
    doi = "10.9999/creator-merge-test.001"

    # First upsert: no authors
    ref_no_authors = ReferenceRecord(
        title="Author Merge Test Paper",
        item_type="article-journal",
        year=2024,
        doi=doi,
        authors=[],
    )
    ref_id = repo.upsert_reference(ref_no_authors)

    authors_after_first = repo.get_creators_for_reference(ref_id, "author")
    assert len(authors_after_first) == 0, "Expected 0 authors after first upsert"

    # Second upsert: same DOI, now with two authors
    ref_with_authors = ReferenceRecord(
        title="Author Merge Test Paper",
        item_type="article-journal",
        year=2024,
        doi=doi,
        authors=[
            CreatorRecord(family="Garcia", given="Maria"),
            CreatorRecord(family="Kim", given="Jae-won"),
        ],
    )
    ref_id2 = repo.upsert_reference(ref_with_authors)

    assert ref_id2 == ref_id, "Should have updated the same record"
    authors_after_second = repo.get_creators_for_reference(ref_id, "author")
    assert len(authors_after_second) == 2, (
        f"Expected 2 authors after second upsert, got {len(authors_after_second)}"
    )
    families = {a.family for a in authors_after_second}
    assert families == {"Garcia", "Kim"}


def test_upsert_preserves_authors_when_updating_other_fields(repo):
    """Upsert with authors first, then upsert again updating only metadata.

    Authors must be preserved (not zeroed out) after the second upsert.
    """
    doi = "10.9999/creator-merge-test.002"

    # First upsert: with authors
    ref_with_authors = ReferenceRecord(
        title="Preservation Test Paper",
        item_type="article-journal",
        year=2023,
        doi=doi,
        authors=[
            CreatorRecord(family="Patel", given="Priya"),
        ],
    )
    ref_id = repo.upsert_reference(ref_with_authors)

    # Second upsert: same DOI, same authors list, but updated abstract
    ref_updated = ReferenceRecord(
        title="Preservation Test Paper",
        item_type="article-journal",
        year=2023,
        doi=doi,
        abstract="Now with an abstract.",
        authors=[
            CreatorRecord(family="Patel", given="Priya"),
        ],
    )
    ref_id2 = repo.upsert_reference(ref_updated)

    assert ref_id2 == ref_id
    authors = repo.get_creators_for_reference(ref_id, "author")
    assert len(authors) == 1, (
        f"Expected 1 author after second upsert, got {len(authors)}"
    )
    assert authors[0].family == "Patel"

    # Confirm the abstract was actually updated
    fetched = repo.get_reference(ref_id)
    assert fetched.abstract == "Now with an abstract."


def test_upsert_conservative_preserves_authors_when_incoming_empty(repo):
    """Conservative upsert with empty authors must NOT clear existing authors.

    Regression: xishi reproduced author count dropping from 1 to 0 when a
    metadata-only conservative upsert passed authors=[].
    """
    doi = "10.9999/creator-merge-test.004"

    # First upsert: with one author
    ref_with_author = ReferenceRecord(
        title="Conservative Empty Authors Test",
        item_type="article-journal",
        year=2024,
        doi=doi,
        authors=[CreatorRecord(family="Nakamura", given="Yuki")],
    )
    ref_id = repo.upsert_reference(ref_with_author)
    assert len(repo.get_creators_for_reference(ref_id, "author")) == 1

    # Second upsert: same DOI, no authors (metadata-only update)
    ref_no_authors = ReferenceRecord(
        title="Conservative Empty Authors Test",
        item_type="article-journal",
        year=2024,
        doi=doi,
        abstract="A new abstract added later.",
        authors=[],
    )
    ref_id2 = repo.upsert_reference(ref_no_authors, merge_policy="conservative")

    assert ref_id2 == ref_id, "Should update the same record"
    authors = repo.get_creators_for_reference(ref_id, "author")
    assert len(authors) == 1, (
        f"Conservative upsert with empty authors must preserve existing authors, "
        f"got {len(authors)}"
    )
    assert authors[0].family == "Nakamura"

    # The new field should still be applied
    fetched = repo.get_reference(ref_id)
    assert fetched.abstract == "A new abstract added later."


def test_upsert_overwrite_clears_authors_when_incoming_empty(repo):
    """Overwrite upsert with empty authors IS allowed to clear existing authors."""
    doi = "10.9999/creator-merge-test.005"

    ref_with_author = ReferenceRecord(
        title="Overwrite Empty Authors Test",
        item_type="article-journal",
        year=2024,
        doi=doi,
        authors=[CreatorRecord(family="Okafor", given="Chidi")],
    )
    ref_id = repo.upsert_reference(ref_with_author)
    assert len(repo.get_creators_for_reference(ref_id, "author")) == 1

    ref_no_authors = ReferenceRecord(
        title="Overwrite Empty Authors Test",
        item_type="article-journal",
        year=2024,
        doi=doi,
        authors=[],
    )
    ref_id2 = repo.upsert_reference(ref_no_authors, merge_policy="overwrite")

    assert ref_id2 == ref_id
    authors = repo.get_creators_for_reference(ref_id, "author")
    assert len(authors) == 0, (
        f"Overwrite upsert with empty authors must clear creators, got {len(authors)}"
    )


def test_upsert_reduces_author_count_on_overwrite(repo):
    """upsert with merge_policy='overwrite' replaces the author list entirely."""
    doi = "10.9999/creator-merge-test.003"

    ref_first = ReferenceRecord(
        title="Overwrite Test Paper",
        item_type="article-journal",
        year=2022,
        doi=doi,
        authors=[
            CreatorRecord(family="Alpha", given="A"),
            CreatorRecord(family="Beta", given="B"),
            CreatorRecord(family="Gamma", given="G"),
        ],
    )
    ref_id = repo.upsert_reference(ref_first)
    assert len(repo.get_creators_for_reference(ref_id, "author")) == 3

    # Overwrite with a single author
    ref_second = ReferenceRecord(
        title="Overwrite Test Paper",
        item_type="article-journal",
        year=2022,
        doi=doi,
        authors=[
            CreatorRecord(family="Solo", given="S"),
        ],
    )
    ref_id2 = repo.upsert_reference(ref_second, merge_policy="overwrite")

    assert ref_id2 == ref_id
    authors = repo.get_creators_for_reference(ref_id, "author")
    assert len(authors) == 1, (
        f"Expected 1 author after overwrite upsert, got {len(authors)}"
    )
    assert authors[0].family == "Solo"
