"""CitationRepository — all database access for references and related records."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from citalio.db.models import (
    AttachmentRecord,
    CreatorRecord,
    NoteRecord,
    ProvenanceEvent,
    ReferenceRecord,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class CitationRepository:
    """Provides all database operations for the citations domain."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # References
    # ------------------------------------------------------------------

    def create_reference(self, record: ReferenceRecord) -> str:
        """Insert a new reference row and link all creators atomically.

        All operations (INSERT reference + creator lookups/inserts + link rows)
        are committed in a single transaction so that a partial failure cannot
        leave a reference row without its creator links.

        Returns the record's id.
        """
        self._conn.execute(
            """
            INSERT INTO "references" (
                id, citekey, item_type, title, year, publication_title,
                volume, issue, pages, publisher, place, edition,
                doi, isbn, issn, pmid, arxiv_id, url, abstract, language,
                canonical_source, confidence_score, metadata_json,
                created_at, updated_at
            ) VALUES (
                :id, :citekey, :item_type, :title, :year, :publication_title,
                :volume, :issue, :pages, :publisher, :place, :edition,
                :doi, :isbn, :issn, :pmid, :arxiv_id, :url, :abstract, :language,
                :canonical_source, :confidence_score, :metadata_json,
                :created_at, :updated_at
            )
            """,
            record.model_dump(exclude={"authors", "editors"}),
        )
        # Use tx-level helpers (no intermediate commits) so the whole operation
        # is committed atomically at the end.
        for pos, author in enumerate(record.authors):
            creator_id = self._get_or_create_creator_tx(author)
            self._link_creator_tx(record.id, creator_id, "author", pos)
        for pos, editor in enumerate(record.editors):
            creator_id = self._get_or_create_creator_tx(editor)
            self._link_creator_tx(record.id, creator_id, "editor", pos)
        self._conn.commit()

        return record.id

    def upsert_reference(
        self, record: ReferenceRecord, merge_policy: str = "conservative"
    ) -> str:
        """Insert or update a reference atomically.

        merge_policy='conservative': only overwrite NULL fields in existing row.
        merge_policy='overwrite': replace all fields.

        The UPDATE + creator-link re-sync are committed in a single transaction
        so that a partial failure cannot leave the reference in an inconsistent
        creator state.

        Returns the canonical id.
        """
        existing: Optional[ReferenceRecord] = None

        # Try to find an existing match
        if record.doi:
            existing = self.find_by_doi(record.doi)
        if existing is None and record.citekey:
            existing = self.find_by_citekey(record.citekey)
        if existing is None:
            existing = self.find_by_title_year(record.title, record.year)

        if existing is None:
            return self.create_reference(record)

        if merge_policy == "overwrite":
            merged = record.model_copy(update={"id": existing.id, "created_at": existing.created_at, "updated_at": _now_iso()})
        else:
            # Conservative: keep existing non-null values
            existing_dict = existing.model_dump(exclude={"authors", "editors"})
            new_dict = record.model_dump(exclude={"authors", "editors"})
            for key, val in existing_dict.items():
                if key in ("id", "created_at"):
                    new_dict[key] = val
                elif val is not None and key not in ("updated_at",):
                    new_dict[key] = val
            new_dict["updated_at"] = _now_iso()
            merged = ReferenceRecord(**new_dict)
            # Conservative creator merge: only replace if incoming list is non-empty.
            # An empty incoming list is treated as "no update", not "clear creators".
            merged_authors = record.authors if record.authors else existing.authors
            merged_editors = record.editors if record.editors else existing.editors
            merged = merged.model_copy(update={"authors": merged_authors, "editors": merged_editors})

        self._conn.execute(
            """
            UPDATE "references" SET
                citekey=:citekey, item_type=:item_type, title=:title, year=:year,
                publication_title=:publication_title, volume=:volume, issue=:issue,
                pages=:pages, publisher=:publisher, place=:place, edition=:edition,
                doi=:doi, isbn=:isbn, issn=:issn, pmid=:pmid, arxiv_id=:arxiv_id,
                url=:url, abstract=:abstract, language=:language,
                canonical_source=:canonical_source, confidence_score=:confidence_score,
                metadata_json=:metadata_json, updated_at=:updated_at
            WHERE id=:id
            """,
            merged.model_dump(exclude={"authors", "editors"}),
        )

        # Re-sync creator links inside the same transaction: delete existing
        # links and re-insert from the merged record.  We only touch
        # reference_creators rows; the creators table itself is left intact
        # (creators are shared entities).
        self._conn.execute(
            "DELETE FROM reference_creators WHERE reference_id = ?",
            (existing.id,),
        )
        for pos, author in enumerate(merged.authors):
            creator_id = self._get_or_create_creator_tx(author)
            self._link_creator_tx(existing.id, creator_id, "author", pos)
        for pos, editor in enumerate(merged.editors):
            creator_id = self._get_or_create_creator_tx(editor)
            self._link_creator_tx(existing.id, creator_id, "editor", pos)
        self._conn.commit()

        return existing.id

    def list_references(self, limit: Optional[int] = None) -> list[ReferenceRecord]:
        """Return all references ordered by year DESC, title ASC.

        If limit is None, all records are returned.  Pass an integer to cap
        the result set (useful for large libraries or MCP resource listings).
        """
        if limit is not None:
            rows = self._conn.execute(
                'SELECT * FROM "references" ORDER BY year DESC, title ASC LIMIT ?',
                (limit,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                'SELECT * FROM "references" ORDER BY year DESC, title ASC'
            ).fetchall()
        return [self._row_to_reference(r) for r in rows]

    def get_reference(self, reference_id: str) -> Optional[ReferenceRecord]:
        """Fetch a single reference by its UUID."""
        row = self._conn.execute(
            'SELECT * FROM "references" WHERE id = ?', (reference_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_reference(row)

    def find_by_doi(self, doi: str) -> Optional[ReferenceRecord]:
        row = self._conn.execute(
            'SELECT * FROM "references" WHERE doi = ?', (doi.strip(),)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_reference(row)

    def find_by_citekey(self, citekey: str) -> Optional[ReferenceRecord]:
        row = self._conn.execute(
            'SELECT * FROM "references" WHERE citekey = ?', (citekey,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_reference(row)

    def find_by_title_year(
        self, title: str, year: Optional[int]
    ) -> Optional[ReferenceRecord]:
        """Find a reference by exact title match (and year if provided)."""
        if year is not None:
            row = self._conn.execute(
                'SELECT * FROM "references" WHERE title = ? AND year = ?',
                (title, year),
            ).fetchone()
        else:
            row = self._conn.execute(
                'SELECT * FROM "references" WHERE title = ?', (title,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_reference(row)

    def search_references(self, query: str, limit: int = 20) -> list[ReferenceRecord]:
        """Case-insensitive LIKE search over title, abstract, and citekey."""
        pattern = f"%{query}%"
        rows = self._conn.execute(
            """
            SELECT * FROM "references"
            WHERE title LIKE ? OR abstract LIKE ? OR citekey LIKE ?
            ORDER BY year DESC, title ASC
            LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        ).fetchall()
        return [self._row_to_reference(r) for r in rows]

    # ------------------------------------------------------------------
    # Creators
    # ------------------------------------------------------------------

    def _get_or_create_creator_tx(self, creator: CreatorRecord) -> str:
        """Like get_or_create_creator but without committing.

        Intended for use inside multi-step operations (create_reference,
        upsert_reference) where a single final commit provides atomicity.
        """
        if creator.orcid:
            row = self._conn.execute(
                "SELECT id FROM creators WHERE orcid = ?", (creator.orcid,)
            ).fetchone()
            if row:
                return row["id"]

        if creator.family and creator.given:
            row = self._conn.execute(
                "SELECT id FROM creators WHERE family = ? AND given = ?",
                (creator.family, creator.given),
            ).fetchone()
            if row:
                return row["id"]
        elif creator.literal:
            row = self._conn.execute(
                "SELECT id FROM creators WHERE literal = ?", (creator.literal,)
            ).fetchone()
            if row:
                return row["id"]

        # Not found — insert without committing
        self._conn.execute(
            """
            INSERT INTO creators (id, given, family, literal, orcid, created_at, updated_at)
            VALUES (:id, :given, :family, :literal, :orcid, :created_at, :updated_at)
            """,
            creator.model_dump(),
        )
        return creator.id

    def _link_creator_tx(
        self, reference_id: str, creator_id: str, role: str, position: int
    ) -> None:
        """Like link_creator_to_reference but without committing.

        Intended for use inside multi-step operations (create_reference,
        upsert_reference) where a single final commit provides atomicity.
        """
        self._conn.execute(
            """
            INSERT OR IGNORE INTO reference_creators (reference_id, creator_id, role, position)
            VALUES (?, ?, ?, ?)
            """,
            (reference_id, creator_id, role, position),
        )

    def add_creator(self, creator: CreatorRecord) -> str:
        self._conn.execute(
            """
            INSERT INTO creators (id, given, family, literal, orcid, created_at, updated_at)
            VALUES (:id, :given, :family, :literal, :orcid, :created_at, :updated_at)
            """,
            creator.model_dump(),
        )
        self._conn.commit()
        return creator.id

    def get_or_create_creator(self, creator: CreatorRecord) -> str:
        """Return the id of a matching creator, inserting if not found.

        Matching logic: exact (family, given) or orcid or literal.
        """
        if creator.orcid:
            row = self._conn.execute(
                "SELECT id FROM creators WHERE orcid = ?", (creator.orcid,)
            ).fetchone()
            if row:
                return row["id"]

        if creator.family and creator.given:
            row = self._conn.execute(
                "SELECT id FROM creators WHERE family = ? AND given = ?",
                (creator.family, creator.given),
            ).fetchone()
            if row:
                return row["id"]
        elif creator.literal:
            row = self._conn.execute(
                "SELECT id FROM creators WHERE literal = ?", (creator.literal,)
            ).fetchone()
            if row:
                return row["id"]

        # Not found — insert
        return self.add_creator(creator)

    def link_creator_to_reference(
        self, reference_id: str, creator_id: str, role: str, position: int
    ) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO reference_creators (reference_id, creator_id, role, position)
            VALUES (?, ?, ?, ?)
            """,
            (reference_id, creator_id, role, position),
        )
        self._conn.commit()

    def get_creators_for_reference(
        self, reference_id: str, role: str = "author"
    ) -> list[CreatorRecord]:
        rows = self._conn.execute(
            """
            SELECT c.* FROM creators c
            JOIN reference_creators rc ON rc.creator_id = c.id
            WHERE rc.reference_id = ? AND rc.role = ?
            ORDER BY rc.position ASC
            """,
            (reference_id, role),
        ).fetchall()
        return [CreatorRecord(**dict(row)) for row in rows]

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    def add_attachment(self, reference_id: str, attachment: AttachmentRecord) -> str:
        att = attachment.model_copy(update={"reference_id": reference_id})
        self._conn.execute(
            """
            INSERT INTO attachments (
                id, reference_id, kind, path, mime_type, sha256,
                source_url, acquired_via, source_payload_json, created_at, updated_at
            ) VALUES (
                :id, :reference_id, :kind, :path, :mime_type, :sha256,
                :source_url, :acquired_via, :source_payload_json, :created_at, :updated_at
            )
            """,
            att.model_dump(),
        )
        self._conn.commit()
        return att.id

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def add_note(self, reference_id: str, note: NoteRecord) -> str:
        n = note.model_copy(update={"reference_id": reference_id})
        self._conn.execute(
            """
            INSERT INTO notes (
                id, reference_id, kind, text, source, confidence,
                metadata_json, created_at, updated_at
            ) VALUES (
                :id, :reference_id, :kind, :text, :source, :confidence,
                :metadata_json, :created_at, :updated_at
            )
            """,
            n.model_dump(),
        )
        self._conn.commit()
        return n.id

    # ------------------------------------------------------------------
    # Provenance
    # ------------------------------------------------------------------

    def record_provenance(self, event: ProvenanceEvent) -> str:
        self._conn.execute(
            """
            INSERT INTO provenance_events (
                id, reference_id, event_type, source, source_record_id,
                before_json, after_json, confidence, message, created_at
            ) VALUES (
                :id, :reference_id, :event_type, :source, :source_record_id,
                :before_json, :after_json, :confidence, :message, :created_at
            )
            """,
            event.model_dump(),
        )
        self._conn.commit()
        return event.id

    def list_notes(self, reference_id: str) -> list[NoteRecord]:
        """Return all notes for a reference, ordered by creation time."""
        rows = self._conn.execute(
            "SELECT * FROM notes WHERE reference_id = ? ORDER BY created_at ASC",
            (reference_id,),
        ).fetchall()
        return [NoteRecord(**dict(r)) for r in rows]

    def list_attachments(self, reference_id: str) -> list[AttachmentRecord]:
        """Return all attachments for a reference."""
        rows = self._conn.execute(
            "SELECT * FROM attachments WHERE reference_id = ? ORDER BY created_at ASC",
            (reference_id,),
        ).fetchall()
        return [AttachmentRecord(**dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _row_to_reference(self, row: sqlite3.Row) -> ReferenceRecord:
        d = dict(row)
        ref = ReferenceRecord(**d)
        ref = ref.model_copy(
            update={
                "authors": self.get_creators_for_reference(ref.id, "author"),
                "editors": self.get_creators_for_reference(ref.id, "editor"),
            }
        )
        return ref
