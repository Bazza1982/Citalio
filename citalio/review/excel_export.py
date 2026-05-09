"""Generate an Excel review sheet for citation candidates in a document project."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from citalio.db.project_repository import DocumentCitationRepository
from citalio.db.repository import CitationRepository

_HEADERS = [
    "decision_id",
    "project_id",
    "anchor_id",
    "anchor_text",
    "paragraph_id",
    "reference_id",
    "citekey",
    "title",
    "year",
    "authors",
    "cited_for",
    "decision_state",
    "selected_reason",
    "confidence",
]

_EDITABLE_COLS = {"cited_for", "decision_state", "selected_reason", "confidence"}

_STATE_CHOICES = (
    "candidate / approved / rejected / needs_repair / repaired / inserted / rendered / validated"
)


def generate_review_excel(
    conn: sqlite3.Connection,
    project_id: str,
    out_path: Path,
    states: Optional[list[str]] = None,
) -> int:
    """Write citation candidates for a project to an Excel review sheet.

    states: filter by decision_state (default: all states).
    Returns the number of rows written (excluding header).
    """
    proj_repo = DocumentCitationRepository(conn)
    ref_repo = CitationRepository(conn)

    project = proj_repo.get_project(project_id)
    if project is None:
        raise ValueError(f"Project not found: {project_id}")

    decisions = proj_repo.list_candidates(project_id, states=states)

    # Build anchor lookup
    anchors_by_id = {a.id: a for a in proj_repo.list_anchors(project_id)}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Citation Review"

    # --- Header row ---
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(fill_type="solid", fgColor="1F3864")
    for col_idx, header in enumerate(_HEADERS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    editable_fill = PatternFill(fill_type="solid", fgColor="FFF2CC")
    editable_cols_idx = {
        col_idx
        for col_idx, h in enumerate(_HEADERS, start=1)
        if h in _EDITABLE_COLS
    }

    # --- Data rows ---
    for row_idx, decision in enumerate(decisions, start=2):
        anchor = anchors_by_id.get(decision.anchor_id or "")
        ref = ref_repo.get_reference(decision.reference_id) if decision.reference_id else None

        authors_str = ""
        if ref and ref.authors:
            authors_str = "; ".join(a.display_name for a in ref.authors)

        values = [
            decision.id,
            project_id,
            decision.anchor_id or "",
            anchor.anchor_text if anchor else "",
            decision.paragraph_id or "",
            decision.reference_id or "",
            ref.citekey if ref else "",
            ref.title if ref else "",
            ref.year if ref else "",
            authors_str,
            decision.cited_for or "",
            decision.decision_state,
            decision.selected_reason or "",
            decision.confidence,
        ]

        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            if col_idx in editable_cols_idx:
                cell.fill = editable_fill
            cell.alignment = Alignment(wrap_text=True)

    # --- Add instructions sheet ---
    ws_info = wb.create_sheet("Instructions")
    ws_info["A1"] = "Citalio Citation Review Sheet"
    ws_info["A1"].font = Font(bold=True, size=14)
    ws_info["A3"] = "Editable columns (highlighted yellow in Citation Review):"
    for i, col in enumerate(_EDITABLE_COLS, start=4):
        ws_info.cell(row=i, column=1, value=f"  {col}")
    ws_info["A9"] = "Valid decision_state values:"
    ws_info["A10"] = _STATE_CHOICES

    # --- Column widths ---
    col_widths = {
        "decision_id": 38, "project_id": 38, "anchor_id": 38,
        "anchor_text": 40, "paragraph_id": 16, "reference_id": 38,
        "citekey": 20, "title": 50, "year": 8, "authors": 30,
        "cited_for": 40, "decision_state": 18, "selected_reason": 30, "confidence": 12,
    }
    for col_idx, header in enumerate(_HEADERS, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = col_widths.get(header, 16)

    ws.freeze_panes = "A2"

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return len(decisions)
