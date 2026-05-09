"""DocumentCitationRepository — all database access for document projects and decisions."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from citalio.db.models import (
    DocumentAnchorRecord,
    DocumentCitationDecisionRecord,
    DocumentProjectRecord,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class DocumentCitationRepository:
    """Provides all database operations for document projects and citation decisions."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def create_project(self, record: DocumentProjectRecord) -> str:
        self._conn.execute(
            """
            INSERT INTO document_projects (
                id, name, root_path, docx_path, markdown_path,
                sidecar_path, citation_style_id, created_at, updated_at
            ) VALUES (
                :id, :name, :root_path, :docx_path, :markdown_path,
                :sidecar_path, :citation_style_id, :created_at, :updated_at
            )
            """,
            record.model_dump(),
        )
        self._conn.commit()
        return record.id

    def get_project(self, project_id: str) -> Optional[DocumentProjectRecord]:
        row = self._conn.execute(
            "SELECT * FROM document_projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        return DocumentProjectRecord(**dict(row))

    def list_projects(self) -> list[DocumentProjectRecord]:
        rows = self._conn.execute(
            "SELECT * FROM document_projects ORDER BY created_at DESC"
        ).fetchall()
        return [DocumentProjectRecord(**dict(r)) for r in rows]

    def update_project(self, record: DocumentProjectRecord) -> None:
        updated = record.model_copy(update={"updated_at": _now_iso()})
        self._conn.execute(
            """
            UPDATE document_projects SET
                name=:name, root_path=:root_path, docx_path=:docx_path,
                markdown_path=:markdown_path, sidecar_path=:sidecar_path,
                citation_style_id=:citation_style_id, updated_at=:updated_at
            WHERE id=:id
            """,
            updated.model_dump(),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Anchors
    # ------------------------------------------------------------------

    def upsert_anchor(self, anchor: DocumentAnchorRecord) -> str:
        """Insert a new anchor or update status if one with the same id exists."""
        existing = self._conn.execute(
            "SELECT id FROM document_anchors WHERE id = ?", (anchor.id,)
        ).fetchone()
        if existing:
            self._conn.execute(
                """
                UPDATE document_anchors SET
                    paragraph_id=:paragraph_id, sentence_hash=:sentence_hash,
                    surrounding_text_hash=:surrounding_text_hash,
                    anchor_text=:anchor_text, status=:status, updated_at=:updated_at
                WHERE id=:id
                """,
                anchor.model_copy(update={"updated_at": _now_iso()}).model_dump(),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO document_anchors (
                    id, project_id, paragraph_id, sentence_hash,
                    surrounding_text_hash, anchor_text, status, created_at, updated_at
                ) VALUES (
                    :id, :project_id, :paragraph_id, :sentence_hash,
                    :surrounding_text_hash, :anchor_text, :status, :created_at, :updated_at
                )
                """,
                anchor.model_dump(),
            )
        self._conn.commit()
        return anchor.id

    def get_anchor(self, anchor_id: str) -> Optional[DocumentAnchorRecord]:
        row = self._conn.execute(
            "SELECT * FROM document_anchors WHERE id = ?", (anchor_id,)
        ).fetchone()
        if row is None:
            return None
        return DocumentAnchorRecord(**dict(row))

    def list_anchors(
        self, project_id: str, status: Optional[str] = None
    ) -> list[DocumentAnchorRecord]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM document_anchors WHERE project_id = ? AND status = ? ORDER BY created_at ASC",
                (project_id, status),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM document_anchors WHERE project_id = ? ORDER BY created_at ASC",
                (project_id,),
            ).fetchall()
        return [DocumentAnchorRecord(**dict(r)) for r in rows]

    def mark_anchor_stale(self, anchor_id: str, reason: Optional[str] = None) -> None:
        self._conn.execute(
            "UPDATE document_anchors SET status='stale', updated_at=? WHERE id=?",
            (_now_iso(), anchor_id),
        )
        # Move linked decisions to needs_repair
        self._conn.execute(
            """
            UPDATE document_citation_decisions
            SET decision_state='needs_repair', updated_at=?
            WHERE anchor_id=? AND decision_state IN ('candidate','approved')
            """,
            (_now_iso(), anchor_id),
        )
        self._conn.commit()

    def mark_anchor_resolved(self, anchor_id: str) -> None:
        self._conn.execute(
            "UPDATE document_anchors SET status='resolved', updated_at=? WHERE id=?",
            (_now_iso(), anchor_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Citation decisions
    # ------------------------------------------------------------------

    def record_decision(self, decision: DocumentCitationDecisionRecord) -> str:
        self._conn.execute(
            """
            INSERT INTO document_citation_decisions (
                id, project_id, reference_id, citation_marker, anchor_id,
                paragraph_id, sentence_hash, surrounding_text_hash,
                cited_for, selected_reason, decision_state, confidence,
                evidence_json, created_at, updated_at
            ) VALUES (
                :id, :project_id, :reference_id, :citation_marker, :anchor_id,
                :paragraph_id, :sentence_hash, :surrounding_text_hash,
                :cited_for, :selected_reason, :decision_state, :confidence,
                :evidence_json, :created_at, :updated_at
            )
            """,
            decision.model_dump(),
        )
        self._conn.commit()
        return decision.id

    def get_decision(self, decision_id: str) -> Optional[DocumentCitationDecisionRecord]:
        row = self._conn.execute(
            "SELECT * FROM document_citation_decisions WHERE id = ?", (decision_id,)
        ).fetchone()
        if row is None:
            return None
        return DocumentCitationDecisionRecord(**dict(row))

    def list_candidates(
        self,
        project_id: str,
        anchor_id: Optional[str] = None,
        states: Optional[list[str]] = None,
    ) -> list[DocumentCitationDecisionRecord]:
        """List decisions, optionally filtered by anchor and/or state."""
        params: list = [project_id]
        sql = "SELECT * FROM document_citation_decisions WHERE project_id = ?"
        if anchor_id:
            sql += " AND anchor_id = ?"
            params.append(anchor_id)
        if states:
            placeholders = ",".join("?" * len(states))
            sql += f" AND decision_state IN ({placeholders})"
            params.extend(states)
        sql += " ORDER BY created_at ASC"
        rows = self._conn.execute(sql, params).fetchall()
        return [DocumentCitationDecisionRecord(**dict(r)) for r in rows]

    def list_approved_for_rendering(
        self, project_id: str
    ) -> list[DocumentCitationDecisionRecord]:
        return self.list_candidates(project_id, states=["approved", "repaired"])

    def _transition_decision(self, decision_id: str, new_state: str) -> bool:
        """Update a decision's state. Returns True if row existed."""
        result = self._conn.execute(
            "UPDATE document_citation_decisions SET decision_state=?, updated_at=? WHERE id=?",
            (new_state, _now_iso(), decision_id),
        )
        self._conn.commit()
        return result.rowcount > 0

    def approve_decision(self, decision_id: str) -> bool:
        return self._transition_decision(decision_id, "approved")

    def reject_decision(self, decision_id: str, reason: Optional[str] = None) -> bool:
        if reason:
            self._conn.execute(
                "UPDATE document_citation_decisions SET decision_state='rejected', selected_reason=?, updated_at=? WHERE id=?",
                (reason, _now_iso(), decision_id),
            )
            self._conn.commit()
            return True
        return self._transition_decision(decision_id, "rejected")

    def mark_decision_needs_repair(self, decision_id: str) -> bool:
        return self._transition_decision(decision_id, "needs_repair")

    def mark_decision_inserted(self, decision_id: str) -> bool:
        return self._transition_decision(decision_id, "inserted")

    def mark_decision_rendered(self, decision_id: str) -> bool:
        return self._transition_decision(decision_id, "rendered")

    def mark_decision_validated(self, decision_id: str) -> bool:
        return self._transition_decision(decision_id, "validated")

    # ------------------------------------------------------------------
    # Project statistics
    # ------------------------------------------------------------------

    def project_stats(self, project_id: str) -> dict:
        """Return counts of decisions by state for a project."""
        rows = self._conn.execute(
            """
            SELECT decision_state, COUNT(*) as cnt
            FROM document_citation_decisions
            WHERE project_id = ?
            GROUP BY decision_state
            """,
            (project_id,),
        ).fetchall()
        stats = {r["decision_state"]: r["cnt"] for r in rows}
        anchor_rows = self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM document_anchors WHERE project_id = ? GROUP BY status",
            (project_id,),
        ).fetchall()
        stats["anchors"] = {r["status"]: r["cnt"] for r in anchor_rows}
        return stats
