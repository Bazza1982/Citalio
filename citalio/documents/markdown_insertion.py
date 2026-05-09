"""Step 8: Insert citation markers into markdown documents."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from citalio.db.models import ProvenanceEvent
from citalio.db.project_repository import DocumentCitationRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_marker(raw: str) -> str:
    """Normalise a citation marker to pandoc [@key] style."""
    m = raw.strip()
    if m.startswith("[@") and m.endswith("]"):
        return m
    if m.startswith("[") and m.endswith("]"):
        inner = m[1:-1].lstrip("@")
        return f"[@{inner}]"
    if m.startswith("@"):
        return f"[{m}]"
    return f"[@{m}]"


def _marker_present_near(content: str, anchor_pos: int, anchor_len: int, marker: str) -> bool:
    """Return True if marker already appears within the same paragraph as the anchor."""
    para_end = content.find("\n\n", anchor_pos)
    if para_end == -1:
        para_end = len(content)
    context = content[anchor_pos : para_end]
    return marker in context


@dataclass
class InsertionResult:
    inserted: int = 0
    already_present: int = 0
    anchor_not_found: int = 0
    no_marker: int = 0
    details: list[dict] = field(default_factory=list)


def insert_citations(
    conn: sqlite3.Connection,
    project_id: str,
    markdown_path: Path,
    output_path: Optional[Path] = None,
) -> InsertionResult:
    """Insert approved citation markers into *markdown_path*.

    Reads all approved/repaired decisions for *project_id*, locates each
    anchor in the markdown text, and appends any missing citation markers
    immediately after the anchor text.  Running this function twice produces
    the same result (idempotent).

    *output_path* defaults to *markdown_path* (in-place update).
    """
    if output_path is None:
        output_path = markdown_path

    repo = DocumentCitationRepository(conn)
    decisions = repo.list_approved_for_rendering(project_id)
    result = InsertionResult()

    if not decisions:
        return result

    content = markdown_path.read_text(encoding="utf-8")

    # Group decisions by anchor_id so we can insert all markers at once.
    by_anchor: dict[str, list] = {}
    anchorless: list = []
    for d in decisions:
        if d.anchor_id:
            by_anchor.setdefault(d.anchor_id, []).append(d)
        else:
            anchorless.append(d)

    for d in anchorless:
        if not d.citation_marker:
            result.no_marker += 1
            result.details.append({"decision_id": d.id, "status": "no_marker"})
        else:
            result.anchor_not_found += 1
            result.details.append({"decision_id": d.id, "status": "no_anchor"})

    for anchor_id, decs in by_anchor.items():
        anchor = repo.get_anchor(anchor_id)
        if anchor is None or not anchor.anchor_text:
            for d in decs:
                result.anchor_not_found += 1
                result.details.append({"decision_id": d.id, "status": "anchor_record_missing"})
            continue

        anchor_text = anchor.anchor_text
        anchor_pos = content.find(anchor_text)
        if anchor_pos == -1:
            for d in decs:
                result.anchor_not_found += 1
                result.details.append({
                    "decision_id": d.id,
                    "status": "anchor_text_not_in_document",
                    "anchor_text": anchor_text[:80],
                })
            continue

        insert_at = anchor_pos + len(anchor_text)

        for d in decs:
            if not d.citation_marker:
                result.no_marker += 1
                result.details.append({"decision_id": d.id, "status": "no_marker"})
                continue

            formatted = _format_marker(d.citation_marker)

            if _marker_present_near(content, anchor_pos, len(anchor_text), formatted):
                result.already_present += 1
                result.details.append({
                    "decision_id": d.id,
                    "status": "already_present",
                    "marker": formatted,
                })
                # Still transition state if not done yet.
                if d.decision_state not in ("inserted", "rendered", "validated"):
                    repo.mark_decision_inserted(d.id)
                continue

            # Insert the marker into content at the current insert_at position.
            content = content[:insert_at] + formatted + content[insert_at:]
            insert_at += len(formatted)  # advance so next marker appends after

            repo.mark_decision_inserted(d.id)

            event = ProvenanceEvent(
                reference_id=d.reference_id,
                event_type="inserted",
                source="citalio.step8",
                message=f"Inserted {formatted} after: {anchor_text[:60]}",
            )
            conn.execute(
                """
                INSERT INTO provenance_events
                    (id, reference_id, event_type, source, message, created_at)
                VALUES
                    (:id, :reference_id, :event_type, :source, :message, :created_at)
                """,
                event.model_dump(),
            )
            conn.commit()

            result.inserted += 1
            result.details.append({
                "decision_id": d.id,
                "status": "inserted",
                "marker": formatted,
                "anchor_text": anchor_text[:80],
            })

    output_path.write_text(content, encoding="utf-8")
    return result
