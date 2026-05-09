"""Sidecar import and export for Citalio document projects.

A sidecar is a JSON file that captures the citation decisions for one document
project. It can be shared, committed to version control alongside the document,
and re-imported into a fresh Citalio library.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from citalio.db.models import DocumentAnchorRecord, DocumentCitationDecisionRecord
from citalio.db.project_repository import DocumentCitationRepository


def export_sidecar(
    conn: sqlite3.Connection,
    project_id: str,
    out_path: Optional[Path] = None,
) -> dict:
    """Export a project's anchors and decisions to a sidecar dict (and optionally a file).

    Returns the sidecar dict regardless of whether a file was written.
    """
    repo = DocumentCitationRepository(conn)
    project = repo.get_project(project_id)
    if project is None:
        raise ValueError(f"Project not found: {project_id}")

    anchors = repo.list_anchors(project_id)
    decisions = repo.list_candidates(project_id)

    sidecar = {
        "citalio_sidecar_version": 1,
        "project_id": project_id,
        "project_name": project.name,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "anchors": [a.model_dump() for a in anchors],
        "decisions": [d.model_dump() for d in decisions],
    }

    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8")

    return sidecar


def import_sidecar(
    conn: sqlite3.Connection,
    project_id: str,
    sidecar_path: Path,
    merge: bool = True,
) -> tuple[int, int]:
    """Import anchors and decisions from a sidecar JSON file.

    If merge=True (default), existing records are skipped (upsert by id).
    If merge=False, the function still upserts — existing records are updated.

    Returns (anchors_imported, decisions_imported).
    """
    data = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))

    if data.get("citalio_sidecar_version", 1) != 1:
        raise ValueError(
            f"Unsupported sidecar version: {data.get('citalio_sidecar_version')}"
        )

    repo = DocumentCitationRepository(conn)

    anchors_imported = 0
    for anchor_data in data.get("anchors", []):
        anchor_data["project_id"] = project_id
        anchor = DocumentAnchorRecord(**anchor_data)
        repo.upsert_anchor(anchor)
        anchors_imported += 1

    decisions_imported = 0
    existing_decision_ids: set[str] = set()
    if merge:
        existing_rows = conn.execute(
            "SELECT id FROM document_citation_decisions WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        existing_decision_ids = {r["id"] for r in existing_rows}

    for dec_data in data.get("decisions", []):
        dec_data["project_id"] = project_id
        decision = DocumentCitationDecisionRecord(**dec_data)
        if merge and decision.id in existing_decision_ids:
            continue
        # Insert or replace
        conn.execute(
            """
            INSERT OR REPLACE INTO document_citation_decisions (
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
        decisions_imported += 1

    conn.commit()
    return anchors_imported, decisions_imported
