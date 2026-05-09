"""Tests for Phase 5: MCP server tool implementations.

We test the server factory and all tool functions against a real in-memory
SQLite database — no actual MCP transport is required.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from citalio.db.connection import open_and_migrate
from citalio.db.models import (
    DocumentCitationDecisionRecord,
    DocumentProjectRecord,
    ReferenceRecord,
)
from citalio.db.project_repository import DocumentCitationRepository
from citalio.db.repository import CitationRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def library_dir(tmp_path: Path) -> Path:
    """A temporary library directory with an initialised DB."""
    # open_and_migrate() expects the library *root directory*, not the .db file.
    conn = open_and_migrate(tmp_path)
    conn.close()
    return tmp_path


@pytest.fixture()
def conn(library_dir: Path) -> sqlite3.Connection:
    # open_and_migrate() expects the library *root directory*.
    return open_and_migrate(library_dir)


@pytest.fixture()
def ref_repo(conn: sqlite3.Connection) -> CitationRepository:
    return CitationRepository(conn)


@pytest.fixture()
def proj_repo(conn: sqlite3.Connection) -> DocumentCitationRepository:
    return DocumentCitationRepository(conn)


def _make_server(library_dir: Path):
    """Create a FastMCP server pointed at the temp library."""
    try:
        from citalio.mcp.server import create_server
    except ImportError:
        pytest.skip("citalio[mcp] not installed")
    return create_server(library_dir)


# ---------------------------------------------------------------------------
# Repository additions (list_notes, list_attachments, mark_decision_needs_repair)
# ---------------------------------------------------------------------------

class TestRepositoryAdditions:
    def test_list_notes_empty(self, ref_repo, conn):
        record = ReferenceRecord(title="Test Paper", item_type="article")
        ref_id = ref_repo.create_reference(record)
        notes = ref_repo.list_notes(ref_id)
        assert notes == []

    def test_list_notes_returns_notes(self, ref_repo, conn):
        from citalio.db.models import NoteRecord

        record = ReferenceRecord(title="Notes Paper", item_type="article")
        ref_id = ref_repo.create_reference(record)
        ref_repo.add_note(ref_id, NoteRecord(reference_id=ref_id, text="Hello", kind="user_note", source="test"))
        ref_repo.add_note(ref_id, NoteRecord(reference_id=ref_id, text="World", kind="summary", source="test"))
        notes = ref_repo.list_notes(ref_id)
        assert len(notes) == 2
        assert {n.text for n in notes} == {"Hello", "World"}

    def test_list_attachments_empty(self, ref_repo, conn):
        record = ReferenceRecord(title="Attach Paper", item_type="article")
        ref_id = ref_repo.create_reference(record)
        atts = ref_repo.list_attachments(ref_id)
        assert atts == []

    def test_list_attachments_returns_attachments(self, ref_repo, conn):
        from citalio.db.models import AttachmentRecord

        record = ReferenceRecord(title="Attach Paper2", item_type="article")
        ref_id = ref_repo.create_reference(record)
        ref_repo.add_attachment(ref_id, AttachmentRecord(reference_id=ref_id, path="/tmp/a.pdf", kind="pdf"))
        atts = ref_repo.list_attachments(ref_id)
        assert len(atts) == 1
        assert atts[0].path == "/tmp/a.pdf"

    def test_mark_decision_needs_repair(self, proj_repo, ref_repo, conn):
        record = ReferenceRecord(title="Repair Paper", item_type="article")
        ref_id = ref_repo.create_reference(record)
        proj = DocumentProjectRecord(name="Repair Project")
        proj_id = proj_repo.create_project(proj)
        decision = DocumentCitationDecisionRecord(
            project_id=proj_id,
            reference_id=ref_id,
            decision_state="approved",
        )
        dec_id = proj_repo.record_decision(decision)
        ok = proj_repo.mark_decision_needs_repair(dec_id)
        assert ok is True
        updated = proj_repo.get_decision(dec_id)
        assert updated.decision_state == "needs_repair"


# ---------------------------------------------------------------------------
# MCP server creation
# ---------------------------------------------------------------------------

class TestServerCreation:
    def test_create_server_returns_fastmcp(self, library_dir):
        server = _make_server(library_dir)
        assert server is not None
        # FastMCP has a name attribute
        assert server.name == "Citalio"


# ---------------------------------------------------------------------------
# MCP tool: search_references
# ---------------------------------------------------------------------------

class TestSearchReferencesTool:
    def _get_tool(self, library_dir):
        server = _make_server(library_dir)
        # Access the underlying tool function via the FastMCP tool registry
        return server

    def test_search_empty_library(self, library_dir):
        server = _make_server(library_dir)
        # Call the tool function directly — FastMCP wraps functions under ._tool_manager
        tool_fn = _find_tool(server, "search_references")
        result = json.loads(tool_fn(query="anything"))
        assert isinstance(result, list)
        assert result == []

    def test_search_finds_reference(self, library_dir, conn):
        ref_repo = CitationRepository(conn)
        record = ReferenceRecord(title="Institutional Theory", item_type="article", year=2020)
        ref_repo.create_reference(record)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "search_references")
        result = json.loads(tool_fn(query="Institutional"))
        assert len(result) == 1
        assert result[0]["title"] == "Institutional Theory"


# ---------------------------------------------------------------------------
# MCP tool: get_reference / find_by_doi
# ---------------------------------------------------------------------------

class TestGetReferenceTool:
    def test_get_reference_not_found(self, library_dir):
        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "get_reference")
        result = json.loads(tool_fn(reference_id="nonexistent-id"))
        assert "error" in result

    def test_get_reference_found(self, library_dir, conn):
        ref_repo = CitationRepository(conn)
        record = ReferenceRecord(title="Found Paper", item_type="article", doi="10.1000/test")
        ref_id = ref_repo.create_reference(record)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "get_reference")
        result = json.loads(tool_fn(reference_id=ref_id))
        assert result["title"] == "Found Paper"
        assert result["doi"] == "10.1000/test"

    def test_find_by_doi_not_found(self, library_dir):
        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "find_by_doi")
        result = json.loads(tool_fn(doi="10.9999/missing"))
        assert result["found"] is False

    def test_find_by_doi_found(self, library_dir, conn):
        ref_repo = CitationRepository(conn)
        record = ReferenceRecord(title="DOI Paper", item_type="article", doi="10.1234/abc")
        ref_repo.create_reference(record)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "find_by_doi")
        result = json.loads(tool_fn(doi="10.1234/abc"))
        assert result["found"] is True
        assert result["title"] == "DOI Paper"


# ---------------------------------------------------------------------------
# MCP tool: create_reference
# ---------------------------------------------------------------------------

class TestCreateReferenceTool:
    def test_creates_reference(self, library_dir, conn):
        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "create_reference")
        result = json.loads(tool_fn(title="New MCP Ref", item_type="book", year=2024))
        assert "id" in result
        assert result["title"] == "New MCP Ref"

        # Verify in DB
        ref_repo = CitationRepository(conn)
        ref = ref_repo.get_reference(result["id"])
        assert ref is not None
        assert ref.title == "New MCP Ref"
        assert ref.year == 2024

    def test_create_writes_provenance(self, library_dir, conn):
        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "create_reference")
        result = json.loads(tool_fn(title="Provenance Ref", doi="10.0/prov"))

        rows = conn.execute(
            "SELECT * FROM provenance_events WHERE reference_id = ? AND source = 'mcp'",
            (result["id"],),
        ).fetchall()
        assert len(rows) >= 1


# ---------------------------------------------------------------------------
# MCP tool: add_note
# ---------------------------------------------------------------------------

class TestAddNoteTool:
    def test_add_note_success(self, library_dir, conn):
        ref_repo = CitationRepository(conn)
        record = ReferenceRecord(title="Note Target", item_type="article")
        ref_id = ref_repo.create_reference(record)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "add_note")
        result = json.loads(tool_fn(reference_id=ref_id, text="Important insight", kind="user_note"))
        assert "id" in result
        assert result["reference_id"] == ref_id

    def test_add_note_missing_reference(self, library_dir):
        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "add_note")
        result = json.loads(tool_fn(reference_id="no-such-id", text="oops"))
        assert "error" in result


# ---------------------------------------------------------------------------
# MCP tool: project tools
# ---------------------------------------------------------------------------

class TestProjectTools:
    def test_create_project(self, library_dir, conn):
        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "create_project")
        result = json.loads(tool_fn(name="MCP Project"))
        assert "id" in result
        assert result["name"] == "MCP Project"

        proj_repo = DocumentCitationRepository(conn)
        proj = proj_repo.get_project(result["id"])
        assert proj is not None
        assert proj.name == "MCP Project"

    def test_load_project_not_found(self, library_dir):
        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "load_project")
        result = json.loads(tool_fn(project_id="nonexistent"))
        assert "error" in result

    def test_load_project_with_stats(self, library_dir, conn):
        proj_repo = DocumentCitationRepository(conn)
        proj = DocumentProjectRecord(name="Stats Project")
        proj_id = proj_repo.create_project(proj)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "load_project")
        result = json.loads(tool_fn(project_id=proj_id))
        assert result["name"] == "Stats Project"
        assert "stats" in result


# ---------------------------------------------------------------------------
# MCP tool: approve_candidate / reject_candidate / repair_candidate
# ---------------------------------------------------------------------------

class TestDecisionTools:
    def _setup_decision(self, library_dir, conn) -> tuple[str, str]:
        ref_repo = CitationRepository(conn)
        record = ReferenceRecord(title="Decision Paper", item_type="article")
        ref_id = ref_repo.create_reference(record)

        proj_repo = DocumentCitationRepository(conn)
        proj = DocumentProjectRecord(name="Decision Project")
        proj_id = proj_repo.create_project(proj)
        decision = DocumentCitationDecisionRecord(
            project_id=proj_id,
            reference_id=ref_id,
            decision_state="candidate",
        )
        dec_id = proj_repo.record_decision(decision)
        return ref_id, dec_id

    def test_approve_candidate(self, library_dir, conn):
        ref_id, dec_id = self._setup_decision(library_dir, conn)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "approve_candidate")
        result = json.loads(tool_fn(decision_id=dec_id))
        assert result["state"] == "approved"

    def test_reject_candidate(self, library_dir, conn):
        ref_id, dec_id = self._setup_decision(library_dir, conn)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "reject_candidate")
        result = json.loads(tool_fn(decision_id=dec_id, reason="Not relevant"))
        assert result["state"] == "rejected"

    def test_repair_candidate(self, library_dir, conn):
        ref_id, dec_id = self._setup_decision(library_dir, conn)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "repair_candidate")
        result = json.loads(tool_fn(decision_id=dec_id))
        assert result["state"] == "needs_repair"

    def test_approve_writes_provenance(self, library_dir, conn):
        ref_id, dec_id = self._setup_decision(library_dir, conn)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "approve_candidate")
        tool_fn(decision_id=dec_id)

        # Re-open and check provenance
        from citalio.db.connection import open_and_migrate
        conn2 = open_and_migrate(library_dir)
        rows = conn2.execute(
            "SELECT * FROM provenance_events WHERE reference_id = ? AND event_type = 'validated'",
            (ref_id,),
        ).fetchall()
        assert len(rows) >= 1

    def test_decision_not_found(self, library_dir):
        server = _make_server(library_dir)
        for tool_name in ("approve_candidate", "reject_candidate", "repair_candidate"):
            tool_fn = _find_tool(server, tool_name)
            result = json.loads(tool_fn(decision_id="no-such-decision"))
            assert "error" in result


# ---------------------------------------------------------------------------
# MCP tool: list_candidates
# ---------------------------------------------------------------------------

class TestListCandidatesTool:
    def test_list_candidates_empty(self, library_dir, conn):
        proj_repo = DocumentCitationRepository(conn)
        proj = DocumentProjectRecord(name="Empty Proj")
        proj_id = proj_repo.create_project(proj)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "list_candidates")
        result = json.loads(tool_fn(project_id=proj_id))
        assert result == []

    def test_list_candidates_with_state_filter(self, library_dir, conn):
        ref_repo = CitationRepository(conn)
        proj_repo = DocumentCitationRepository(conn)
        proj = DocumentProjectRecord(name="Filter Proj")
        proj_id = proj_repo.create_project(proj)

        for title, state in [("A", "candidate"), ("B", "approved"), ("C", "rejected")]:
            r = ReferenceRecord(title=title, item_type="article")
            ref_id = ref_repo.create_reference(r)
            d = DocumentCitationDecisionRecord(
                project_id=proj_id, reference_id=ref_id, decision_state=state
            )
            proj_repo.record_decision(d)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "list_candidates")
        result = json.loads(tool_fn(project_id=proj_id, states=["approved"]))
        assert len(result) == 1
        assert result[0]["decision_state"] == "approved"


# ---------------------------------------------------------------------------
# MCP tool: workflow tools (step8, step10)
# ---------------------------------------------------------------------------

class TestWorkflowTools:
    def test_step8_no_markdown_path(self, library_dir, conn):
        proj_repo = DocumentCitationRepository(conn)
        proj = DocumentProjectRecord(name="No MD")
        proj_id = proj_repo.create_project(proj)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "run_step8_markdown_insertion")
        result = json.loads(tool_fn(project_id=proj_id))
        assert "error" in result

    def test_step8_inserts_markers(self, library_dir, conn, tmp_path):
        md_file = tmp_path / "draft.md"
        md_file.write_text("This is a sentence that needs a citation.\n\nAnother paragraph.\n")

        ref_repo = CitationRepository(conn)
        proj_repo = DocumentCitationRepository(conn)

        record = ReferenceRecord(title="Step8 Paper", item_type="article", citekey="step8paper2020")
        ref_id = ref_repo.create_reference(record)

        proj = DocumentProjectRecord(name="Step8 Project", markdown_path=str(md_file))
        proj_id = proj_repo.create_project(proj)

        from citalio.db.models import DocumentAnchorRecord
        anchor = DocumentAnchorRecord(
            project_id=proj_id,
            anchor_text="This is a sentence that needs a citation.",
            paragraph_id="p1",
        )
        anchor_id = proj_repo.upsert_anchor(anchor)

        decision = DocumentCitationDecisionRecord(
            project_id=proj_id,
            reference_id=ref_id,
            citation_marker="[@step8paper2020]",
            anchor_id=anchor_id,
            decision_state="approved",
        )
        proj_repo.record_decision(decision)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "run_step8_markdown_insertion")
        result = json.loads(tool_fn(project_id=proj_id))
        assert result["inserted"] >= 1

    def test_step10_no_project(self, library_dir):
        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "run_step10_validation")
        result = json.loads(tool_fn(project_id="nonexistent"))
        assert "error" in result

    def test_step10_returns_report(self, library_dir, conn):
        proj_repo = DocumentCitationRepository(conn)
        proj = DocumentProjectRecord(name="Validate Proj")
        proj_id = proj_repo.create_project(proj)
        conn.close()

        server = _make_server(library_dir)
        tool_fn = _find_tool(server, "run_step10_validation")
        result = json.loads(tool_fn(project_id=proj_id))
        assert result.get("project_id") == proj_id
        assert "issues" in result


# ---------------------------------------------------------------------------
# Helpers for accessing FastMCP tools
# ---------------------------------------------------------------------------

def _find_tool(server, name: str):
    """Extract a raw callable from a FastMCP server by tool name.

    FastMCP registers tool functions internally; we access them via the
    _tool_manager._tools dict which maps names to Tool objects, each having
    a .fn attribute.
    """
    tools = server._tool_manager._tools
    if name not in tools:
        available = list(tools.keys())
        raise KeyError(f"Tool {name!r} not found. Available: {available}")
    tool = tools[name]
    # FastMCP Tool has .fn (the raw callable)
    return tool.fn
