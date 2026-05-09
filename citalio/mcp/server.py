"""Citalio MCP server — exposes citation DB and document workflow to AI agents."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:
    raise ImportError(
        "citalio[mcp] is required to run the MCP server. "
        "Install with: pip install 'citalio[mcp]'"
    ) from exc

from citalio.db.connection import open_and_migrate
from citalio.db.models import (
    AttachmentRecord,
    DocumentCitationDecisionRecord,
    DocumentProjectRecord,
    NoteRecord,
    ProvenanceEvent,
    ReferenceRecord,
)
from citalio.db.project_repository import DocumentCitationRepository
from citalio.db.repository import CitationRepository
from citalio.documents.markdown_insertion import insert_citations
from citalio.review.excel_export import generate_review_excel as _gen_excel
from citalio.review.excel_import import apply_review_excel as _apply_excel
from citalio.validation.citation_validator import validate_project


def _library_path() -> Path:
    env = os.environ.get("CITALIO_HOME")
    return Path(env) if env else Path.home() / ".citalio"


def create_server(library: Optional[Path] = None) -> "FastMCP":
    """Create and configure the FastMCP Citalio server."""
    # lib is the library *root directory* — open_and_migrate() expects a
    # directory and appends "citalio.db" itself.  Do NOT pass lib / "citalio.db"
    # here, which would cause open_and_migrate() to treat the .db file as the
    # root directory and then try to open root/citalio.db (a nested path).
    lib = library or _library_path()

    mcp = FastMCP("Citalio")

    def _open():
        return open_and_migrate(lib)

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    @mcp.resource("citalio://library/references")
    def list_references_resource() -> str:
        """All references in the library (up to 200)."""
        conn = _open()
        repo = CitationRepository(conn)
        refs = repo.search_references("", limit=200)
        return json.dumps(
            [r.model_dump(exclude={"authors", "editors"}) for r in refs], default=str
        )

    @mcp.resource("citalio://library/references/{reference_id}")
    def get_reference_resource(reference_id: str) -> str:
        """Full reference record including authors and editors."""
        conn = _open()
        repo = CitationRepository(conn)
        ref = repo.get_reference(reference_id)
        if ref is None:
            return json.dumps({"error": f"Reference {reference_id!r} not found"})
        data = ref.model_dump(exclude={"authors", "editors"})
        data["authors"] = [c.model_dump() for c in repo.get_creators_for_reference(reference_id, "author")]
        data["editors"] = [c.model_dump() for c in repo.get_creators_for_reference(reference_id, "editor")]
        data["notes"] = [n.model_dump() for n in repo.list_notes(reference_id)]
        return json.dumps(data, default=str)

    @mcp.resource("citalio://library/references/{reference_id}/notes")
    def get_reference_notes_resource(reference_id: str) -> str:
        """Notes attached to a reference."""
        conn = _open()
        repo = CitationRepository(conn)
        notes = repo.list_notes(reference_id)
        return json.dumps([n.model_dump() for n in notes], default=str)

    @mcp.resource("citalio://library/references/{reference_id}/chunks")
    def get_reference_chunks_resource(reference_id: str) -> str:
        """Full-text chunks for a reference (returns empty list if none indexed)."""
        conn = _open()
        rows = conn.execute(
            "SELECT * FROM chunks WHERE reference_id = ? ORDER BY chunk_index ASC",
            (reference_id,),
        ).fetchall()
        return json.dumps([dict(r) for r in rows], default=str)

    @mcp.resource("citalio://projects")
    def list_projects_resource() -> str:
        """All document projects."""
        conn = _open()
        repo = DocumentCitationRepository(conn)
        projects = repo.list_projects()
        return json.dumps([p.model_dump() for p in projects], default=str)

    @mcp.resource("citalio://projects/{project_id}")
    def get_project_resource(project_id: str) -> str:
        """Project record with decision statistics."""
        conn = _open()
        repo = DocumentCitationRepository(conn)
        project = repo.get_project(project_id)
        if project is None:
            return json.dumps({"error": f"Project {project_id!r} not found"})
        data = project.model_dump()
        data["stats"] = repo.project_stats(project_id)
        return json.dumps(data, default=str)

    @mcp.resource("citalio://projects/{project_id}/decisions")
    def get_project_decisions_resource(project_id: str) -> str:
        """All citation decisions for a project."""
        conn = _open()
        repo = DocumentCitationRepository(conn)
        decisions = repo.list_candidates(project_id)
        return json.dumps([d.model_dump() for d in decisions], default=str)

    @mcp.resource("citalio://projects/{project_id}/validation")
    def get_project_validation_resource(project_id: str) -> str:
        """Run Step 10 validation and return the report."""
        conn = _open()
        repo = DocumentCitationRepository(conn)
        project = repo.get_project(project_id)
        if project is None:
            return json.dumps({"error": f"Project {project_id!r} not found"})
        md_path = Path(project.markdown_path) if project.markdown_path else None
        report = validate_project(conn, project_id, md_path)
        return json.dumps(report.to_dict(), default=str)

    # ------------------------------------------------------------------
    # Library tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def search_references(query: str, limit: int = 20) -> str:
        """Search references by keyword (title, abstract, citekey).

        Returns a JSON list of matching reference records.
        """
        conn = _open()
        repo = CitationRepository(conn)
        refs = repo.search_references(query, limit=limit)
        return json.dumps(
            [r.model_dump(exclude={"authors", "editors"}) for r in refs], default=str
        )

    @mcp.tool()
    def get_reference(reference_id: str) -> str:
        """Get a reference by its UUID, including authors, editors, and notes."""
        conn = _open()
        repo = CitationRepository(conn)
        ref = repo.get_reference(reference_id)
        if ref is None:
            return json.dumps({"error": f"Reference {reference_id!r} not found"})
        data = ref.model_dump(exclude={"authors", "editors"})
        data["authors"] = [c.model_dump() for c in repo.get_creators_for_reference(reference_id, "author")]
        data["editors"] = [c.model_dump() for c in repo.get_creators_for_reference(reference_id, "editor")]
        return json.dumps(data, default=str)

    @mcp.tool()
    def find_by_doi(doi: str) -> str:
        """Look up a reference by DOI. Returns {found: false} if not in library."""
        conn = _open()
        repo = CitationRepository(conn)
        ref = repo.find_by_doi(doi)
        if ref is None:
            return json.dumps({"found": False, "doi": doi})
        data = ref.model_dump(exclude={"authors", "editors"})
        data["found"] = True
        return json.dumps(data, default=str)

    @mcp.tool()
    def create_reference(
        title: str,
        item_type: str = "article",
        year: Optional[int] = None,
        doi: Optional[str] = None,
        citekey: Optional[str] = None,
        publication_title: Optional[str] = None,
        abstract: Optional[str] = None,
        url: Optional[str] = None,
    ) -> str:
        """Create or upsert a reference in the library.

        Uses conservative merge: will not overwrite existing non-null fields.
        Writes a provenance event. Returns the reference ID.
        """
        conn = _open()
        repo = CitationRepository(conn)
        record = ReferenceRecord(
            title=title,
            item_type=item_type,
            year=year,
            doi=doi,
            citekey=citekey,
            publication_title=publication_title,
            abstract=abstract,
            url=url,
        )
        ref_id = repo.upsert_reference(record)
        repo.record_provenance(
            ProvenanceEvent(
                reference_id=ref_id,
                event_type="created",
                source="mcp",
                message=f"Upserted via MCP tool: {title!r}",
            )
        )
        return json.dumps({"id": ref_id, "title": title})

    @mcp.tool()
    def add_note(
        reference_id: str,
        text: str,
        kind: str = "user_note",
        source: str = "mcp",
    ) -> str:
        """Add a note to a reference. Writes a provenance event."""
        conn = _open()
        repo = CitationRepository(conn)
        if repo.get_reference(reference_id) is None:
            return json.dumps({"error": f"Reference {reference_id!r} not found"})
        note = NoteRecord(reference_id=reference_id, text=text, kind=kind, source=source)
        note_id = repo.add_note(reference_id, note)
        repo.record_provenance(
            ProvenanceEvent(
                reference_id=reference_id,
                event_type="repaired",
                source=source,
                message=f"Note added via MCP: kind={kind!r}",
            )
        )
        return json.dumps({"id": note_id, "reference_id": reference_id})

    @mcp.tool()
    def add_attachment(
        reference_id: str,
        path: str,
        kind: str = "pdf",
    ) -> str:
        """Record a file attachment for a reference. path should be a local file path.

        Writes a provenance event.
        """
        conn = _open()
        repo = CitationRepository(conn)
        if repo.get_reference(reference_id) is None:
            return json.dumps({"error": f"Reference {reference_id!r} not found"})
        att = AttachmentRecord(reference_id=reference_id, path=path, kind=kind)
        att_id = repo.add_attachment(reference_id, att)
        repo.record_provenance(
            ProvenanceEvent(
                reference_id=reference_id,
                event_type="downloaded",
                source="mcp",
                message=f"Attachment added via MCP: kind={kind!r}, path={path!r}",
            )
        )
        return json.dumps({"id": att_id, "reference_id": reference_id, "path": path})

    # ------------------------------------------------------------------
    # Project tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def create_project(
        name: str,
        docx_path: Optional[str] = None,
        markdown_path: Optional[str] = None,
    ) -> str:
        """Create a new document citation project."""
        conn = _open()
        repo = DocumentCitationRepository(conn)
        record = DocumentProjectRecord(
            name=name, docx_path=docx_path, markdown_path=markdown_path
        )
        proj_id = repo.create_project(record)
        return json.dumps({"id": proj_id, "name": name})

    @mcp.tool()
    def load_project(project_id: str) -> str:
        """Get project details and decision statistics."""
        conn = _open()
        repo = DocumentCitationRepository(conn)
        project = repo.get_project(project_id)
        if project is None:
            return json.dumps({"error": f"Project {project_id!r} not found"})
        data = project.model_dump()
        data["stats"] = repo.project_stats(project_id)
        return json.dumps(data, default=str)

    @mcp.tool()
    def import_sidecar(project_id: str, sidecar_path: str, merge: bool = True) -> str:
        """Import a JSON sidecar file into a project's citation decisions."""
        from citalio.core.sidecar import import_sidecar as _import_sidecar

        conn = _open()
        repo = DocumentCitationRepository(conn)
        if repo.get_project(project_id) is None:
            return json.dumps({"error": f"Project {project_id!r} not found"})
        stats = _import_sidecar(conn, project_id, Path(sidecar_path), merge=merge)
        return json.dumps(stats)

    @mcp.tool()
    def export_sidecar(project_id: str, out_path: str) -> str:
        """Export a project's citation decisions to a JSON sidecar file."""
        from citalio.core.sidecar import export_sidecar as _export_sidecar

        conn = _open()
        repo = DocumentCitationRepository(conn)
        if repo.get_project(project_id) is None:
            return json.dumps({"error": f"Project {project_id!r} not found"})
        _export_sidecar(conn, project_id, Path(out_path))
        return json.dumps({"out_path": out_path, "project_id": project_id})

    @mcp.tool()
    def list_candidates(
        project_id: str,
        anchor_id: Optional[str] = None,
        states: Optional[list[str]] = None,
    ) -> str:
        """List citation candidates / decisions for a project.

        Optionally filter by anchor_id and/or a list of decision states.
        """
        conn = _open()
        repo = DocumentCitationRepository(conn)
        decisions = repo.list_candidates(project_id, anchor_id=anchor_id, states=states)
        return json.dumps([d.model_dump() for d in decisions], default=str)

    @mcp.tool()
    def approve_candidate(decision_id: str) -> str:
        """Approve a citation candidate. Writes a provenance event."""
        conn = _open()
        proj_repo = DocumentCitationRepository(conn)
        decision = proj_repo.get_decision(decision_id)
        if decision is None:
            return json.dumps({"error": f"Decision {decision_id!r} not found"})
        proj_repo.approve_decision(decision_id)
        if decision.reference_id:
            ref_repo = CitationRepository(conn)
            ref_repo.record_provenance(
                ProvenanceEvent(
                    reference_id=decision.reference_id,
                    event_type="validated",
                    source="mcp",
                    message=f"Decision {decision_id} approved via MCP",
                )
            )
        return json.dumps({"decision_id": decision_id, "state": "approved"})

    @mcp.tool()
    def reject_candidate(decision_id: str, reason: Optional[str] = None) -> str:
        """Reject a citation candidate. Writes a provenance event."""
        conn = _open()
        proj_repo = DocumentCitationRepository(conn)
        decision = proj_repo.get_decision(decision_id)
        if decision is None:
            return json.dumps({"error": f"Decision {decision_id!r} not found"})
        proj_repo.reject_decision(decision_id, reason)
        if decision.reference_id:
            ref_repo = CitationRepository(conn)
            ref_repo.record_provenance(
                ProvenanceEvent(
                    reference_id=decision.reference_id,
                    event_type="repaired",
                    source="mcp",
                    message=f"Decision {decision_id} rejected via MCP: {reason}",
                )
            )
        return json.dumps({"decision_id": decision_id, "state": "rejected"})

    @mcp.tool()
    def repair_candidate(decision_id: str) -> str:
        """Mark a citation decision as needs_repair."""
        conn = _open()
        proj_repo = DocumentCitationRepository(conn)
        if proj_repo.get_decision(decision_id) is None:
            return json.dumps({"error": f"Decision {decision_id!r} not found"})
        proj_repo.mark_decision_needs_repair(decision_id)
        return json.dumps({"decision_id": decision_id, "state": "needs_repair"})

    # ------------------------------------------------------------------
    # Workflow tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def run_step8_markdown_insertion(
        project_id: str, markdown_path: Optional[str] = None
    ) -> str:
        """Run Step 8: insert [@citekey] markers into the markdown document.

        Uses the project's markdown_path if markdown_path is not supplied.
        The output is written in-place. Running twice is idempotent.
        """
        conn = _open()
        repo = DocumentCitationRepository(conn)
        project = repo.get_project(project_id)
        if project is None:
            return json.dumps({"error": f"Project {project_id!r} not found"})
        md = markdown_path or project.markdown_path
        if not md:
            return json.dumps({"error": "No markdown_path configured or supplied."})
        result = insert_citations(conn, project_id, Path(md))
        return json.dumps(
            {
                "inserted": result.inserted,
                "already_present": result.already_present,
                "anchor_not_found": result.anchor_not_found,
                "no_marker": result.no_marker,
            }
        )

    @mcp.tool()
    def run_step10_validation(
        project_id: str, markdown_path: Optional[str] = None
    ) -> str:
        """Run Step 10 validation: check decisions against the markdown document.

        Returns a ValidationReport with any issues found.
        """
        conn = _open()
        repo = DocumentCitationRepository(conn)
        project = repo.get_project(project_id)
        if project is None:
            return json.dumps({"error": f"Project {project_id!r} not found"})
        md = markdown_path or project.markdown_path
        report = validate_project(conn, project_id, Path(md) if md else None)
        return json.dumps(report.to_dict(), default=str)

    @mcp.tool()
    def generate_review_excel(project_id: str, out_path: str) -> str:
        """Generate an Excel review sheet for a project.

        out_path must be a writable .xlsx path. The sheet can be edited and
        then applied back with apply_review_excel.
        """
        conn = _open()
        repo = DocumentCitationRepository(conn)
        if repo.get_project(project_id) is None:
            return json.dumps({"error": f"Project {project_id!r} not found"})
        _gen_excel(conn, project_id, Path(out_path))
        return json.dumps({"out_path": out_path, "project_id": project_id})

    @mcp.tool()
    def apply_review_excel(project_id: str, excel_path: str) -> str:
        """Apply a completed Excel review sheet back to the database.

        Returns the count of rows processed and rows updated.
        """
        conn = _open()
        repo = DocumentCitationRepository(conn)
        if repo.get_project(project_id) is None:
            return json.dumps({"error": f"Project {project_id!r} not found"})
        processed, updated = _apply_excel(conn, project_id, Path(excel_path))
        return json.dumps(
            {"processed": processed, "updated": updated, "project_id": project_id}
        )

    return mcp
