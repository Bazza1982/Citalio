"""Parse a completed Excel review sheet and apply decisions back to the DB."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

from citalio.db.project_repository import DocumentCitationRepository

_VALID_STATES = frozenset({
    "candidate", "approved", "rejected", "needs_repair",
    "repaired", "inserted", "rendered", "validated",
})


def apply_review_excel(
    conn: sqlite3.Connection,
    project_id: str,
    xlsx_path: Path,
) -> tuple[int, int]:
    """Read a review sheet and apply edited fields back to the DB.

    Only the editable columns are applied: cited_for, decision_state,
    selected_reason, confidence.

    Returns (rows_processed, rows_updated).
    """
    wb = openpyxl.load_workbook(Path(xlsx_path), read_only=True, data_only=True)
    ws = wb["Citation Review"]

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return 0, 0

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    col = {name: idx for idx, name in enumerate(headers)}

    required = {"decision_id", "cited_for", "decision_state", "selected_reason", "confidence"}
    missing = required - set(col.keys())
    if missing:
        raise ValueError(f"Review sheet is missing columns: {missing}")

    repo = DocumentCitationRepository(conn)
    now = datetime.now(timezone.utc).isoformat()

    rows_processed = 0
    rows_updated = 0

    for row in rows[1:]:
        if not any(row):
            continue

        decision_id = str(row[col["decision_id"]]).strip() if row[col["decision_id"]] else ""
        if not decision_id:
            continue

        cited_for = row[col["cited_for"]]
        state_raw = row[col["decision_state"]]
        reason = row[col["selected_reason"]]
        confidence_raw = row[col["confidence"]]

        state = str(state_raw).strip() if state_raw is not None else ""
        if state and state not in _VALID_STATES:
            raise ValueError(
                f"Invalid decision_state '{state}' on row for decision {decision_id}. "
                f"Valid values: {sorted(_VALID_STATES)}"
            )

        try:
            confidence = float(confidence_raw) if confidence_raw is not None else None
        except (ValueError, TypeError):
            confidence = None

        # Build update, only setting fields that have a value in the sheet
        parts = ["updated_at = ?"]
        params: list = [now]

        if cited_for is not None:
            parts.append("cited_for = ?")
            params.append(str(cited_for).strip() if cited_for else None)
        if state:
            parts.append("decision_state = ?")
            params.append(state)
        if reason is not None:
            parts.append("selected_reason = ?")
            params.append(str(reason).strip() if reason else None)
        if confidence is not None:
            parts.append("confidence = ?")
            params.append(confidence)

        params.append(decision_id)

        result = conn.execute(
            f"UPDATE document_citation_decisions SET {', '.join(parts)} WHERE id = ?",
            params,
        )
        rows_processed += 1
        if result.rowcount > 0:
            rows_updated += 1

    conn.commit()
    return rows_processed, rows_updated
