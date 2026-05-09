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


# ---------------------------------------------------------------------------
# list_references
# ---------------------------------------------------------------------------

def test_list_references_returns_all(repo):
    repo.create_reference(ReferenceRecord(title="Paper A", year=2020))
    repo.create_reference(ReferenceRecord(title="Paper B", year=2021))
    repo.create_reference(ReferenceRecord(title="Paper C", year=2019))
    all_refs = repo.list_references()
    assert len(all_refs) == 3
    titles = {r.title for r in all_refs}
    assert titles == {"Paper A", "Paper B", "Paper C"}


def test_list_references_with_limit(repo):
    for i in range(5):
        repo.create_reference(ReferenceRecord(title=f"Paper {i}"))
    result = repo.list_references(limit=3)
    assert len(result) == 3


def test_list_references_empty_library(repo):
    assert repo.list_references() == []


def test_list_references_ordered_by_year_desc(repo):
    repo.create_reference(ReferenceRecord(title="Old Paper", year=2010))
    repo.create_reference(ReferenceRecord(title="New Paper", year=2023))
    result = repo.list_references()
    assert result[0].year == 2023
    assert result[1].year == 2010


# ---------------------------------------------------------------------------
# upsert_reference — match by title+year
# ---------------------------------------------------------------------------

def test_upsert_match_by_title_and_year(repo):
    """upsert_reference should find existing record by title+year when no DOI/citekey."""
    ref1 = ReferenceRecord(
        title="A paper without DOI or citekey",
        item_type="article-journal",
        year=2018,
    )
    ref_id = repo.create_reference(ref1)

    # Upsert with same title+year, add an abstract
    ref2 = ReferenceRecord(
        title="A paper without DOI or citekey",
        item_type="article-journal",
        year=2018,
        abstract="Abstract added later.",
    )
    ref_id2 = repo.upsert_reference(ref2)

    assert ref_id2 == ref_id, "Should match by title+year and return same id"
    fetched = repo.get_reference(ref_id)
    assert fetched.abstract == "Abstract added later."


# ---------------------------------------------------------------------------
# search_references edge cases
# ---------------------------------------------------------------------------

def test_search_references_empty_query_returns_all(repo):
    """search_references('') should return all records (LIKE '%%' matches everything)."""
    repo.create_reference(ReferenceRecord(title="Alpha study"))
    repo.create_reference(ReferenceRecord(title="Beta study"))
    results = repo.search_references("", limit=100)
    assert len(results) == 2


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


# ---------------------------------------------------------------------------
# Transaction atomicity — create_reference and upsert_reference rollback tests
# ---------------------------------------------------------------------------

def test_create_reference_rolls_back_on_link_failure(repo):
    """If _link_creator_tx raises during create_reference, no partial reference remains.

    Regression: before the fix, a failed creator-link phase left the reference
    row in the DB; a subsequent successful commit would persist it.

    Reproduction strategy (per xishi):
      1. Monkeypatch _link_creator_tx to fail on the second call.
      2. Call create_reference with two authors — first link succeeds, second raises.
      3. Restore the real helper, create a different reference successfully.
      4. Assert only the good reference exists; the bad one was rolled back.
    """
    call_count = {"n": 0}
    real_link = repo._link_creator_tx

    def failing_link(reference_id, creator_id, role, position):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated link failure on second author")
        return real_link(reference_id, creator_id, role, position)

    bad_ref = ReferenceRecord(
        title="Bad Paper 2024",
        item_type="article-journal",
        year=2024,
        doi="10.bad/atomicity-create",
        authors=[
            CreatorRecord(family="AuthorOne", given="A"),
            CreatorRecord(family="AuthorTwo", given="B"),
        ],
    )

    repo._link_creator_tx = failing_link
    with pytest.raises(RuntimeError, match="simulated link failure"):
        repo.create_reference(bad_ref)
    repo._link_creator_tx = real_link

    # Subsequent successful write must not commit the bad_ref partial state
    good_ref = ReferenceRecord(
        title="Good Paper 2024",
        item_type="article-journal",
        year=2024,
        doi="10.good/atomicity-create",
        authors=[CreatorRecord(family="GoodAuthor", given="G")],
    )
    good_id = repo.create_reference(good_ref)

    # Only the good reference exists
    all_refs = repo.list_references()
    titles = {r.title for r in all_refs}
    assert "Good Paper 2024" in titles, "Good reference must be committed"
    assert "Bad Paper 2024" not in titles, (
        "Failed reference must not appear — rollback was not effective"
    )

    # Creator links for bad_ref's id must not exist
    bad_author_links = repo.get_creators_for_reference(bad_ref.id, "author")
    assert len(bad_author_links) == 0, "Partial creator links from failed tx must be gone"

    # Good reference is fully intact
    fetched_good = repo.get_reference(good_id)
    assert fetched_good is not None
    assert len(fetched_good.authors) == 1
    assert fetched_good.authors[0].family == "GoodAuthor"


def test_upsert_reference_rolls_back_on_link_failure(repo):
    """If _link_creator_tx raises during upsert_reference (update path), the
    update is rolled back and the original record is preserved.

    Ensures upsert_reference has the same try/except rollback guard as
    create_reference.
    """
    # Insert an initial reference that will be the target of the failing upsert
    original = ReferenceRecord(
        title="Upsert Atomicity Paper",
        item_type="article-journal",
        year=2023,
        doi="10.upsert/atomicity",
        authors=[CreatorRecord(family="OriginalAuthor", given="O")],
    )
    original_id = repo.create_reference(original)

    call_count = {"n": 0}
    real_link = repo._link_creator_tx

    def failing_link(reference_id, creator_id, role, position):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated link failure during upsert")
        return real_link(reference_id, creator_id, role, position)

    # Attempt to upsert with two new authors — second link will fail
    bad_upsert = ReferenceRecord(
        title="Upsert Atomicity Paper",
        item_type="article-journal",
        year=2023,
        doi="10.upsert/atomicity",
        abstract="This abstract should not be committed.",
        authors=[
            CreatorRecord(family="NewAuthorA", given="A"),
            CreatorRecord(family="NewAuthorB", given="B"),
        ],
    )

    repo._link_creator_tx = failing_link
    with pytest.raises(RuntimeError, match="simulated link failure"):
        repo.upsert_reference(bad_upsert, merge_policy="overwrite")
    repo._link_creator_tx = real_link

    # Original reference must be unchanged (abstract not applied, authors intact)
    fetched = repo.get_reference(original_id)
    assert fetched is not None
    # Abstract should not have been committed (rollback)
    assert fetched.abstract is None or fetched.abstract != "This abstract should not be committed."
    # Original author must still be linked (or no authors if rollback removed the delete too)
    # The important thing is NewAuthorA/NewAuthorB are not present
    authors = repo.get_creators_for_reference(original_id, "author")
    author_families = {a.family for a in authors}
    assert "NewAuthorA" not in author_families, "Rolled-back authors must not persist"
    assert "NewAuthorB" not in author_families, "Rolled-back authors must not persist"
