"""Tests for Phase 3: document projects, anchors, decisions, sidecar, and Excel review."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from citalio.db.connection import open_and_migrate
from citalio.db.models import (
    DocumentAnchorRecord,
    DocumentCitationDecisionRecord,
    DocumentProjectRecord,
    ReferenceRecord,
)
from citalio.db.project_repository import DocumentCitationRepository
from citalio.db.repository import CitationRepository


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test_citalio.db"
    c = open_and_migrate(tmp_path)
    yield c
    c.close()


@pytest.fixture
def proj_repo(conn):
    return DocumentCitationRepository(conn)


@pytest.fixture
def sample_project(proj_repo):
    record = DocumentProjectRecord(name="Test Thesis", docx_path="/tmp/thesis.docx")
    proj_repo.create_project(record)
    return record


@pytest.fixture
def sample_anchor(proj_repo, sample_project):
    anchor = DocumentAnchorRecord(
        project_id=sample_project.id,
        paragraph_id="para-001",
        anchor_text="institutions shape behaviour",
        sentence_hash="abc123",
    )
    proj_repo.upsert_anchor(anchor)
    return anchor


@pytest.fixture
def sample_decision(proj_repo, sample_project, sample_anchor):
    decision = DocumentCitationDecisionRecord(
        project_id=sample_project.id,
        anchor_id=sample_anchor.id,
        citation_marker="[1]",
        cited_for="Institutional theory",
        decision_state="candidate",
        confidence=0.75,
    )
    proj_repo.record_decision(decision)
    return decision


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------

class TestProjectCRUD:
    def test_create_and_get(self, proj_repo, sample_project):
        fetched = proj_repo.get_project(sample_project.id)
        assert fetched is not None
        assert fetched.name == "Test Thesis"
        assert fetched.docx_path == "/tmp/thesis.docx"

    def test_get_nonexistent(self, proj_repo):
        assert proj_repo.get_project("no-such-id") is None

    def test_list_projects(self, proj_repo, sample_project):
        projects = proj_repo.list_projects()
        assert any(p.id == sample_project.id for p in projects)

    def test_update_project(self, proj_repo, sample_project):
        updated = sample_project.model_copy(update={"name": "Updated Name"})
        proj_repo.update_project(updated)
        fetched = proj_repo.get_project(sample_project.id)
        assert fetched.name == "Updated Name"


# ---------------------------------------------------------------------------
# Anchor CRUD
# ---------------------------------------------------------------------------

class TestAnchorCRUD:
    def test_upsert_and_get(self, proj_repo, sample_project, sample_anchor):
        fetched = proj_repo.get_anchor(sample_anchor.id)
        assert fetched is not None
        assert fetched.anchor_text == "institutions shape behaviour"
        assert fetched.status == "active"

    def test_upsert_updates_existing(self, proj_repo, sample_anchor):
        updated = sample_anchor.model_copy(update={"anchor_text": "new text"})
        proj_repo.upsert_anchor(updated)
        fetched = proj_repo.get_anchor(sample_anchor.id)
        assert fetched.anchor_text == "new text"

    def test_list_anchors(self, proj_repo, sample_project, sample_anchor):
        anchors = proj_repo.list_anchors(sample_project.id)
        assert any(a.id == sample_anchor.id for a in anchors)

    def test_mark_anchor_stale(self, proj_repo, sample_project, sample_anchor, sample_decision):
        proj_repo.mark_anchor_stale(sample_anchor.id)
        fetched_anchor = proj_repo.get_anchor(sample_anchor.id)
        assert fetched_anchor.status == "stale"
        fetched_dec = proj_repo.get_decision(sample_decision.id)
        assert fetched_dec.decision_state == "needs_repair"

    def test_mark_anchor_resolved(self, proj_repo, sample_anchor):
        proj_repo.mark_anchor_resolved(sample_anchor.id)
        fetched = proj_repo.get_anchor(sample_anchor.id)
        assert fetched.status == "resolved"


# ---------------------------------------------------------------------------
# Decision CRUD
# ---------------------------------------------------------------------------

class TestDecisionCRUD:
    def test_record_and_get(self, proj_repo, sample_decision):
        fetched = proj_repo.get_decision(sample_decision.id)
        assert fetched is not None
        assert fetched.decision_state == "candidate"
        assert fetched.confidence == 0.75

    def test_approve(self, proj_repo, sample_decision):
        ok = proj_repo.approve_decision(sample_decision.id)
        assert ok is True
        fetched = proj_repo.get_decision(sample_decision.id)
        assert fetched.decision_state == "approved"

    def test_reject_with_reason(self, proj_repo, sample_decision):
        ok = proj_repo.reject_decision(sample_decision.id, reason="wrong topic")
        assert ok is True
        fetched = proj_repo.get_decision(sample_decision.id)
        assert fetched.decision_state == "rejected"
        assert fetched.selected_reason == "wrong topic"

    def test_list_candidates_all(self, proj_repo, sample_project, sample_decision):
        decisions = proj_repo.list_candidates(sample_project.id)
        assert any(d.id == sample_decision.id for d in decisions)

    def test_list_candidates_by_state(self, proj_repo, sample_project, sample_decision):
        proj_repo.approve_decision(sample_decision.id)
        approved = proj_repo.list_candidates(sample_project.id, states=["approved"])
        assert any(d.id == sample_decision.id for d in approved)
        candidates = proj_repo.list_candidates(sample_project.id, states=["candidate"])
        assert not any(d.id == sample_decision.id for d in candidates)

    def test_list_approved_for_rendering(self, proj_repo, sample_project, sample_decision):
        proj_repo.approve_decision(sample_decision.id)
        approved = proj_repo.list_approved_for_rendering(sample_project.id)
        assert any(d.id == sample_decision.id for d in approved)

    def test_transition_inserted_rendered_validated(self, proj_repo, sample_decision):
        proj_repo.approve_decision(sample_decision.id)
        proj_repo.mark_decision_inserted(sample_decision.id)
        proj_repo.mark_decision_rendered(sample_decision.id)
        proj_repo.mark_decision_validated(sample_decision.id)
        fetched = proj_repo.get_decision(sample_decision.id)
        assert fetched.decision_state == "validated"

    def test_approve_nonexistent(self, proj_repo):
        ok = proj_repo.approve_decision("no-such-id")
        assert ok is False


# ---------------------------------------------------------------------------
# Project stats
# ---------------------------------------------------------------------------

class TestProjectStats:
    def test_stats(self, proj_repo, sample_project, sample_decision):
        proj_repo.approve_decision(sample_decision.id)
        stats = proj_repo.project_stats(sample_project.id)
        assert stats.get("approved", 0) == 1
        assert "anchors" in stats


# ---------------------------------------------------------------------------
# Sidecar import/export
# ---------------------------------------------------------------------------

class TestSidecar:
    def test_export_and_reimport(
        self, conn, proj_repo, sample_project, sample_anchor, sample_decision, tmp_path
    ):
        from citalio.core.sidecar import export_sidecar, import_sidecar

        sidecar_path = tmp_path / "sidecar.json"
        sidecar = export_sidecar(conn, sample_project.id, out_path=sidecar_path)

        assert sidecar_path.exists()
        assert sidecar["project_name"] == "Test Thesis"
        assert len(sidecar["anchors"]) == 1
        assert len(sidecar["decisions"]) == 1

        # Import into a second project
        proj2 = DocumentProjectRecord(name="Project 2")
        proj_repo.create_project(proj2)
        a_count, d_count = import_sidecar(conn, proj2.id, sidecar_path, merge=False)
        assert a_count == 1
        assert d_count == 1

        decisions = proj_repo.list_candidates(proj2.id)
        assert len(decisions) == 1

    def test_export_returns_dict_without_file(
        self, conn, proj_repo, sample_project, sample_anchor, sample_decision
    ):
        from citalio.core.sidecar import export_sidecar

        sidecar = export_sidecar(conn, sample_project.id)
        assert isinstance(sidecar, dict)
        assert sidecar["citalio_sidecar_version"] == 1

    def test_import_merge_skips_duplicates(
        self, conn, proj_repo, sample_project, sample_anchor, sample_decision, tmp_path
    ):
        from citalio.core.sidecar import export_sidecar, import_sidecar

        sidecar_path = tmp_path / "sidecar.json"
        export_sidecar(conn, sample_project.id, out_path=sidecar_path)

        # Import again with merge=True — decision already exists, should be skipped
        _, d_count = import_sidecar(conn, sample_project.id, sidecar_path, merge=True)
        assert d_count == 0

    def test_import_nonexistent_project_raises(self, conn, tmp_path):
        from citalio.core.sidecar import export_sidecar

        with pytest.raises(ValueError, match="Project not found"):
            export_sidecar(conn, "no-such-project-id")


# ---------------------------------------------------------------------------
# Excel review round-trip
# ---------------------------------------------------------------------------

class TestExcelReview:
    def test_generate_and_apply(
        self, conn, proj_repo, sample_project, sample_anchor, sample_decision, tmp_path
    ):
        from citalio.review.excel_export import generate_review_excel
        from citalio.review.excel_import import apply_review_excel

        xlsx_path = tmp_path / "review.xlsx"
        count = generate_review_excel(conn, sample_project.id, xlsx_path)
        assert count == 1
        assert xlsx_path.exists()

        # Manually edit the file: set decision_state to approved
        import openpyxl
        wb = openpyxl.load_workbook(xlsx_path)
        ws = wb["Citation Review"]
        headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
        state_col = headers.index("decision_state") + 1
        ws.cell(2, state_col).value = "approved"
        wb.save(xlsx_path)

        processed, updated = apply_review_excel(conn, sample_project.id, xlsx_path)
        assert processed == 1
        assert updated == 1

        fetched = proj_repo.get_decision(sample_decision.id)
        assert fetched.decision_state == "approved"

    def test_generate_with_state_filter(
        self, conn, proj_repo, sample_project, sample_anchor, sample_decision, tmp_path
    ):
        from citalio.review.excel_export import generate_review_excel

        xlsx_path = tmp_path / "review.xlsx"
        # Filter to 'approved' only — should return 0 rows (decision is still candidate)
        count = generate_review_excel(conn, sample_project.id, xlsx_path, states=["approved"])
        assert count == 0
