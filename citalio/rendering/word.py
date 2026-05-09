"""Step 9: Render [@key] citation markers in Word documents.

.. warning::
    **EXPERIMENTAL — NOT YET WIRED INTO CLI/MCP**

    This module is parked pending a safer implementation of
    ``_replace_in_paragraph()``.  The current approach removes every run from
    a paragraph and writes a single new run, which collapses mixed formatting
    (bold, italic, font overrides, hyperlinks, etc.) and violates the core
    plan guardrail that Word rendering must not destroy document structure.

    Do NOT import ``render_docx`` from production code paths until the
    paragraph-level replacement is rewritten to operate run-by-run without
    removing existing runs.  See the tracker issue for the planned approach.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MARKER_RE = re.compile(r"\[@([^\]]+)\]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RenderingResult:
    rendered_decisions: int = 0
    markers_replaced: int = 0
    markers_not_in_doc: int = 0
    bibliography_entries: int = 0
    details: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Citation formatting helpers
# ---------------------------------------------------------------------------

def _authors_inline(authors) -> str:
    names = [a.family or a.literal or "Unknown" for a in authors]
    if not names:
        return "Unknown"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    return f"{names[0]} et al."


def _format_inline(ref) -> str:
    author_part = _authors_inline(ref.authors) if ref.authors else "Unknown"
    year_part = str(ref.year) if ref.year else "n.d."
    return f"({author_part}, {year_part})"


def _format_bibliography_entry(ref) -> str:
    if ref.authors:
        parts: list[str] = []
        for a in ref.authors:
            if a.family and a.given:
                initials = ". ".join(g[0] for g in a.given.split() if g) + "."
                parts.append(f"{a.family}, {initials}")
            elif a.family:
                parts.append(a.family)
            elif a.literal:
                parts.append(a.literal)
        if len(parts) == 1:
            authors_str = parts[0]
        elif len(parts) <= 7:
            authors_str = ", ".join(parts[:-1]) + ", & " + parts[-1]
        else:
            authors_str = ", ".join(parts[:6]) + ", ... " + parts[-1]
    else:
        authors_str = "Unknown Author"

    year = f"({ref.year})" if ref.year else "(n.d.)"
    title = ref.title or "Untitled"
    entry = f"{authors_str} {year}. {title}."

    if ref.publication_title:
        pub = ref.publication_title
        if ref.volume:
            pub += f", {ref.volume}"
            if ref.issue:
                pub += f"({ref.issue})"
        if ref.pages:
            pub += f", {ref.pages}"
        entry += f" {pub}."
    elif ref.publisher:
        entry += f" {ref.publisher}."

    if ref.doi:
        entry += f" https://doi.org/{ref.doi}"
    elif ref.url:
        entry += f" {ref.url}"

    return entry.strip()


# ---------------------------------------------------------------------------
# Paragraph-level marker replacement
# ---------------------------------------------------------------------------

def _replace_in_paragraph(para, citekey_map: dict[str, str]) -> int:
    """Replace [@key] markers in one paragraph. Returns count replaced."""
    full_text = "".join(run.text for run in para.runs)
    if not MARKER_RE.search(full_text):
        return 0

    count = 0

    def _sub(m: re.Match) -> str:
        nonlocal count
        key = m.group(1).strip()
        if key in citekey_map:
            count += 1
            return citekey_map[key]
        return m.group(0)

    new_text = MARKER_RE.sub(_sub, full_text)
    if count == 0:
        return 0

    # Preserve basic formatting from the first run
    saved = {"bold": None, "italic": None, "size": None, "name": None}
    if para.runs:
        first = para.runs[0]
        saved["bold"] = first.bold
        saved["italic"] = first.italic
        try:
            saved["size"] = first.font.size
            saved["name"] = first.font.name
        except Exception:
            pass

    # Remove all existing runs
    for run in list(para.runs):
        run._element.getparent().remove(run._element)

    # Write new single run
    new_run = para.add_run(new_text)
    if saved["bold"] is not None:
        new_run.bold = saved["bold"]
    if saved["italic"] is not None:
        new_run.italic = saved["italic"]
    try:
        if saved["size"]:
            new_run.font.size = saved["size"]
        if saved["name"]:
            new_run.font.name = saved["name"]
    except Exception:
        pass

    return count


def _replace_in_doc(doc, citekey_map: dict[str, str]) -> int:
    """Replace markers across all paragraphs and table cells. Returns total count."""
    total = 0
    for para in doc.paragraphs:
        total += _replace_in_paragraph(para, citekey_map)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    total += _replace_in_paragraph(para, citekey_map)
    return total


def _markers_in_doc(doc) -> set[str]:
    """Collect all citekeys still present in the document."""
    keys: set[str] = set()
    for para in doc.paragraphs:
        for m in MARKER_RE.finditer(para.text):
            keys.add(m.group(1).strip())
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for m in MARKER_RE.finditer(para.text):
                        keys.add(m.group(1).strip())
    return keys


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_docx(
    conn: sqlite3.Connection,
    project_id: str,
    docx_path: Path,
    output_path: Optional[Path] = None,
    bibliography: bool = True,
    *,
    _allow_experimental: bool = False,
) -> RenderingResult:
    """Replace [@key] markers in *docx_path* with formatted inline citations.

    .. warning::
        **EXPERIMENTAL** — this function is not yet wired into the production
        CLI or MCP server.  Call it only from tests or experimental scripts,
        and pass ``_allow_experimental=True`` to acknowledge the risk.

        The underlying ``_replace_in_paragraph()`` implementation strips all
        runs from each paragraph and rewrites a single run, which collapses
        mixed formatting.  This will be fixed before production use.

    Reads all decisions in 'inserted', 'approved', or 'repaired' states,
    replaces their markers in the Word document, and optionally appends a
    References bibliography section.

    *output_path* defaults to ``<stem>_rendered.docx`` next to *docx_path*
    (copy-on-write; the original is never modified in place).
    """
    if not _allow_experimental:
        raise NotImplementedError(
            "render_docx() is experimental and not yet production-ready.  "
            "Pass _allow_experimental=True to use it in tests/scripts, "
            "or wait for the tracked fix to _replace_in_paragraph()."
        )
    try:
        from docx import Document
    except ImportError:
        raise ImportError(
            "python-docx is required: pip install 'citalio[word]'"
        )

    from citalio.db.models import ProvenanceEvent
    from citalio.db.project_repository import DocumentCitationRepository
    from citalio.db.repository import CitationRepository

    if output_path is None:
        output_path = docx_path.parent / (docx_path.stem + "_rendered.docx")

    proj_repo = DocumentCitationRepository(conn)
    ref_repo = CitationRepository(conn)
    result = RenderingResult()

    decisions = proj_repo.list_candidates(
        project_id,
        states=["inserted", "approved", "repaired"],
    )

    if not decisions:
        doc = Document(docx_path)
        doc.save(output_path)
        return result

    # Build citekey → inline-text and citekey → reference lookup
    citekey_inline: dict[str, str] = {}
    citekey_ref: dict[str, object] = {}
    citekey_decisions: dict[str, list[str]] = {}

    for d in decisions:
        if not d.citation_marker:
            result.details.append({"decision_id": d.id, "status": "no_marker"})
            continue
        key = d.citation_marker.strip().lstrip("@")
        citekey_decisions.setdefault(key, []).append(d.id)

        if d.reference_id and key not in citekey_inline:
            ref = ref_repo.get_reference(d.reference_id)
            if ref:
                ref.authors = ref_repo.get_creators_for_reference(ref.id, "author")
                citekey_inline[key] = _format_inline(ref)
                citekey_ref[key] = ref

    doc = Document(docx_path)

    # Scan document for known marker keys before replacement
    keys_in_doc = _markers_in_doc(doc)

    # Replace markers
    result.markers_replaced = _replace_in_doc(doc, citekey_inline)

    # Record outcomes per citekey
    for key, decision_ids in citekey_decisions.items():
        in_doc = key in keys_in_doc
        for did in decision_ids:
            if in_doc:
                proj_repo.mark_decision_rendered(did)
                result.rendered_decisions += 1
                d = proj_repo.get_decision(did)
                if d and d.reference_id:
                    event = ProvenanceEvent(
                        reference_id=d.reference_id,
                        event_type="rendered",
                        source="citalio.step9",
                        message=f"Rendered [@{key}] in {output_path.name}",
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
                result.details.append({"decision_id": did, "status": "rendered", "key": key})
            else:
                result.markers_not_in_doc += 1
                result.details.append({"decision_id": did, "status": "marker_not_in_doc", "key": key})

    # Append bibliography
    if bibliography and citekey_ref:
        doc.add_page_break()
        doc.add_heading("References", level=1)

        sorted_refs = sorted(
            citekey_ref.values(),
            key=lambda r: (
                (r.authors[0].family or r.authors[0].literal or "") if r.authors else ""
            ).lower()
            or (r.title or "").lower(),
        )
        for ref in sorted_refs:
            doc.add_paragraph(_format_bibliography_entry(ref))
            result.bibliography_entries += 1

    doc.save(output_path)
    return result
