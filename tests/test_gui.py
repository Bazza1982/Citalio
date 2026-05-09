"""Tests for the Citalio GUI FastAPI application."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from citalio.db.connection import open_and_migrate
from citalio.db.models import (
    DocumentCitationDecisionRecord,
    DocumentProjectRecord,
    ReferenceRecord,
)
from citalio.db.project_repository import DocumentCitationRepository
from citalio.db.repository import CitationRepository
from citalio.gui.api import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_library(tmp_path):
    """Return a temporary library directory with an initialised DB."""
    return tmp_path


@pytest.fixture()
def client(tmp_library):
    """Return a TestClient wired to a fresh in-memory library."""
    app = create_app(library=tmp_library)
    return TestClient(app)


@pytest.fixture()
def populated(tmp_library):
    """Populate the DB with one reference, one project, and two decisions."""
    conn = open_and_migrate(tmp_library)

    # Reference
    ref = ReferenceRecord(
        title="Institutional Theory in Organisational Studies",
        year=2003,
        citekey="dimaggio2003",
        doi="10.1000/test.doi",
        abstract="A foundational text on institutional theory.",
    )
    ref_repo = CitationRepository(conn)
    ref_id = ref_repo.create_reference(ref)

    # Project
    project = DocumentProjectRecord(name="PhD Thesis Chapter 2")
    proj_repo = DocumentCitationRepository(conn)
    project_id = proj_repo.create_project(project)

    # Decisions
    d1 = DocumentCitationDecisionRecord(
        project_id=project_id,
        reference_id=ref_id,
        citation_marker="dimaggio2003",
        cited_for="Foundational institutional theory",
        decision_state="candidate",
        confidence=0.9,
    )
    d2 = DocumentCitationDecisionRecord(
        project_id=project_id,
        reference_id=ref_id,
        citation_marker="dimaggio2003b",
        cited_for="Secondary citation",
        decision_state="approved",
        confidence=0.75,
    )
    proj_repo.record_decision(d1)
    proj_repo.record_decision(d2)

    conn.close()

    return {
        "ref_id": ref_id,
        "project_id": project_id,
        "decision1_id": d1.id,
        "decision2_id": d2.id,
    }


# ---------------------------------------------------------------------------
# HTML shell
# ---------------------------------------------------------------------------


class TestHtmlShell:
    def test_root_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_root_contains_citalio_title(self, client):
        r = client.get("/")
        assert "Citalio" in r.text

    def test_root_has_three_nav_buttons(self, client):
        r = client.get("/")
        assert r.text.count("showPanel") >= 3


# ---------------------------------------------------------------------------
# /api/refs
# ---------------------------------------------------------------------------


class TestRefsSearch:
    def test_empty_library_returns_empty_list(self, client):
        r = client.get("/api/refs")
        assert r.status_code == 200
        assert r.json() == []

    def test_search_returns_matching_refs(self, client, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        r = tc.get("/api/refs?q=institutional")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["citekey"] == "dimaggio2003"

    def test_search_no_match_returns_empty(self, client, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        r = tc.get("/api/refs?q=zxqnotfound")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_all_refs(self, client, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        r = tc.get("/api/refs")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_ref_result_has_required_fields(self, client, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        data = tc.get("/api/refs").json()
        ref = data[0]
        assert "id" in ref
        assert "title" in ref
        assert "year" in ref
        assert "authors" in ref


# ---------------------------------------------------------------------------
# /api/refs/{id}
# ---------------------------------------------------------------------------


class TestRefDetail:
    def test_get_ref_detail(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        r = tc.get(f"/api/refs/{populated['ref_id']}")
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "Institutional Theory in Organisational Studies"
        assert data["year"] == 2003
        assert data["doi"] == "10.1000/test.doi"
        assert "abstract" in data
        assert "notes" in data
        assert "attachments" in data
        assert "authors" in data
        assert "editors" in data

    def test_get_ref_not_found_returns_404(self, client):
        r = client.get("/api/refs/nonexistent-id")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# /api/projects
# ---------------------------------------------------------------------------


class TestProjects:
    def test_list_projects_empty(self, client):
        r = client.get("/api/projects")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_projects_returns_created_project(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        r = tc.get("/api/projects")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["name"] == "PhD Thesis Chapter 2"

    def test_list_projects_fields(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        data = tc.get("/api/projects").json()
        p = data[0]
        assert "id" in p
        assert "name" in p
        assert "created_at" in p


# ---------------------------------------------------------------------------
# /api/projects/{id}
# ---------------------------------------------------------------------------


class TestProjectDetail:
    def test_get_project_detail(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        r = tc.get(f"/api/projects/{pid}")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "PhD Thesis Chapter 2"
        assert "stats" in data
        stats = data["stats"]
        assert stats.get("candidate", 0) >= 1
        assert stats.get("approved", 0) >= 1

    def test_get_project_not_found_returns_404(self, client):
        r = client.get("/api/projects/nonexistent-id")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# /api/projects/{id}/decisions
# ---------------------------------------------------------------------------


class TestDecisions:
    def test_list_all_decisions(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        r = tc.get(f"/api/projects/{pid}/decisions")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2

    def test_filter_by_state_candidate(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        r = tc.get(f"/api/projects/{pid}/decisions?state=candidate")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["decision_state"] == "candidate"

    def test_filter_by_state_approved(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        r = tc.get(f"/api/projects/{pid}/decisions?state=approved")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["decision_state"] == "approved"

    def test_decision_fields(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        data = tc.get(f"/api/projects/{pid}/decisions").json()
        d = data[0]
        assert "id" in d
        assert "decision_state" in d
        assert "citation_marker" in d
        assert "confidence" in d


# ---------------------------------------------------------------------------
# /api/projects/{id}/decisions/{did}/approve
# ---------------------------------------------------------------------------


class TestApproveDecision:
    def test_approve_candidate_decision(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        did = populated["decision1_id"]
        r = tc.post(f"/api/projects/{pid}/decisions/{did}/approve")
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

    def test_approve_reflects_in_decisions_list(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        did = populated["decision1_id"]
        tc.post(f"/api/projects/{pid}/decisions/{did}/approve")
        data = tc.get(f"/api/projects/{pid}/decisions?state=approved").json()
        ids = [d["id"] for d in data]
        assert did in ids

    def test_approve_nonexistent_returns_404(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        r = tc.post(f"/api/projects/{pid}/decisions/nonexistent/approve")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# /api/projects/{id}/decisions/{did}/reject
# ---------------------------------------------------------------------------


class TestRejectDecision:
    def test_reject_candidate_decision(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        did = populated["decision1_id"]
        r = tc.post(f"/api/projects/{pid}/decisions/{did}/reject")
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

    def test_reject_with_reason(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        did = populated["decision1_id"]
        r = tc.post(
            f"/api/projects/{pid}/decisions/{did}/reject?reason=Not+relevant"
        )
        assert r.status_code == 200

    def test_reject_reflects_in_decisions_list(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        did = populated["decision1_id"]
        tc.post(f"/api/projects/{pid}/decisions/{did}/reject")
        data = tc.get(f"/api/projects/{pid}/decisions?state=rejected").json()
        ids = [d["id"] for d in data]
        assert did in ids

    def test_reject_nonexistent_returns_404(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        r = tc.post(f"/api/projects/{pid}/decisions/nonexistent/reject")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# /api/projects/{id}/validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_validation_returns_report(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        r = tc.get(f"/api/projects/{pid}/validation")
        assert r.status_code == 200
        data = r.json()
        assert "project_id" in data
        assert "issue_count" in data
        assert "issues" in data
        assert isinstance(data["issues"], list)

    def test_validation_detects_approved_not_inserted(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        data = tc.get(f"/api/projects/{pid}/validation").json()
        # d2 is 'approved' but not inserted — should produce an issue
        types = [i["issue_type"] for i in data["issues"]]
        assert "approved_not_inserted" in types

    def test_validation_issue_fields(self, tmp_library, populated):
        c = create_app(library=tmp_library)
        tc = TestClient(c)
        pid = populated["project_id"]
        data = tc.get(f"/api/projects/{pid}/validation").json()
        if data["issues"]:
            issue = data["issues"][0]
            assert "issue_type" in issue
            assert "description" in issue
