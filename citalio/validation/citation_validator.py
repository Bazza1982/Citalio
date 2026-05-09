"""Step 10: Validate citation decisions against the markdown document and DB."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Optional

from citalio.db.project_repository import DocumentCitationRepository
from citalio.db.repository import CitationRepository
from citalio.validation.reports import ValidationIssue, ValidationReport


# Matches pandoc-style [@key] or [@key1; @key2] citations.
_CITATION_RE = re.compile(r"\[@([^\]]+?)\]")


def _extract_markers_from_markdown(content: str) -> list[str]:
    """Return all individual citekeys found in [@...] markers in *content*."""
    keys = []
    for m in _CITATION_RE.finditer(content):
        # Handle compound markers: [@key1; @key2]
        for part in m.group(1).split(";"):
            key = part.strip().lstrip("@")
            if key:
                keys.append(key)
    return keys


def validate_project(
    conn: sqlite3.Connection,
    project_id: str,
    markdown_path: Optional[Path] = None,
) -> ValidationReport:
    """Run basic Step 10 validation for *project_id*.

    Checks performed:
    - Approved decisions that are still in 'approved' state (not yet inserted).
    - Rejected decisions whose citation_marker appears in the markdown.
    - Citation markers in the markdown that have no matching reference citekey.
    """
    report = ValidationReport(project_id=project_id)
    proj_repo = DocumentCitationRepository(conn)
    ref_repo = CitationRepository(conn)

    all_decisions = proj_repo.list_candidates(project_id)

    # Check 1: approved decisions that are not yet inserted/rendered/validated.
    done_states = {"inserted", "rendered", "validated"}
    for d in all_decisions:
        if d.decision_state == "approved" and d.decision_state not in done_states:
            report.issues.append(
                ValidationIssue(
                    issue_type="approved_not_inserted",
                    description=(
                        f"Decision {d.id} is approved but has not been inserted. "
                        "Run `citalio render markdown` to insert it."
                    ),
                    decision_id=d.id,
                    reference_id=d.reference_id,
                    marker=d.citation_marker,
                )
            )

    # Check 2 & 3 require the markdown file.
    if markdown_path is not None and markdown_path.exists():
        content = markdown_path.read_text(encoding="utf-8")
        markers_in_doc = _extract_markers_from_markdown(content)

        # Index rejected decisions by citation_marker.
        rejected_markers: set[str] = set()
        for d in all_decisions:
            if d.decision_state == "rejected" and d.citation_marker:
                from citalio.documents.markdown_insertion import _format_marker
                formatted = _format_marker(d.citation_marker)
                # Compare normalised keys.
                key = d.citation_marker.strip().lstrip("@")
                rejected_markers.add(key)

        for key in markers_in_doc:
            if key in rejected_markers:
                report.issues.append(
                    ValidationIssue(
                        issue_type="rejected_marker_in_document",
                        description=(
                            f"Marker [@{key}] appears in the document but corresponds "
                            "to a rejected citation decision."
                        ),
                        marker=key,
                    )
                )

        # Check 3: each marker in the document should resolve to a reference.
        for key in set(markers_in_doc):
            ref = ref_repo.find_by_citekey(key)
            if ref is None:
                report.issues.append(
                    ValidationIssue(
                        issue_type="unresolved_marker",
                        description=(
                            f"Marker [@{key}] in the document has no matching "
                            "reference in the Citalio library."
                        ),
                        marker=key,
                    )
                )

    return report
