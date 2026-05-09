"""Pydantic v2 models for Citalio database records."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreatorRecord(BaseModel):
    """Represents a person or organisation credited on a reference."""

    id: str = Field(default_factory=_new_id)
    given: Optional[str] = None
    family: Optional[str] = None
    literal: Optional[str] = None
    orcid: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @property
    def display_name(self) -> str:
        if self.literal:
            return self.literal
        parts = []
        if self.family:
            parts.append(self.family)
        if self.given:
            parts.append(self.given)
        return ", ".join(parts) if parts else "(unknown)"


class ReferenceRecord(BaseModel):
    """Represents one bibliographic reference."""

    id: str = Field(default_factory=_new_id)
    citekey: Optional[str] = None
    item_type: str = "article"
    title: str
    year: Optional[int] = None
    publication_title: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    publisher: Optional[str] = None
    place: Optional[str] = None
    edition: Optional[str] = None
    doi: Optional[str] = None
    isbn: Optional[str] = None
    issn: Optional[str] = None
    pmid: Optional[str] = None
    arxiv_id: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    language: Optional[str] = None
    canonical_source: Optional[str] = None
    confidence_score: float = 0.0
    metadata_json: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    # Transient — not stored directly in the references table
    authors: list[CreatorRecord] = Field(default_factory=list, exclude=True)
    editors: list[CreatorRecord] = Field(default_factory=list, exclude=True)


class AttachmentRecord(BaseModel):
    """Represents a file attachment linked to a reference."""

    id: str = Field(default_factory=_new_id)
    reference_id: str
    kind: str = "file"
    path: str
    mime_type: Optional[str] = None
    sha256: Optional[str] = None
    source_url: Optional[str] = None
    acquired_via: Optional[str] = None
    source_payload_json: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class NoteRecord(BaseModel):
    """Represents a note attached to a reference."""

    id: str = Field(default_factory=_new_id)
    reference_id: str
    kind: str = "user"
    text: str
    source: str = "user"
    confidence: float = 0.0
    metadata_json: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class ProvenanceEvent(BaseModel):
    """Records a change or import event for audit purposes."""

    id: str = Field(default_factory=_new_id)
    reference_id: Optional[str] = None
    event_type: str
    source: str
    source_record_id: Optional[str] = None
    before_json: Optional[str] = None
    after_json: Optional[str] = None
    confidence: Optional[float] = None
    message: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Document project models
# ---------------------------------------------------------------------------


class DocumentProjectRecord(BaseModel):
    """Represents a document writing project with linked citation decisions."""

    id: str = Field(default_factory=_new_id)
    name: str
    root_path: Optional[str] = None
    docx_path: Optional[str] = None
    markdown_path: Optional[str] = None
    sidecar_path: Optional[str] = None
    citation_style_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class DocumentAnchorRecord(BaseModel):
    """A text location in a document that may require a citation."""

    id: str = Field(default_factory=_new_id)
    project_id: str
    paragraph_id: Optional[str] = None
    sentence_hash: Optional[str] = None
    surrounding_text_hash: Optional[str] = None
    anchor_text: Optional[str] = None
    status: str = "active"  # active | stale | resolved
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class DocumentCitationDecisionRecord(BaseModel):
    """A citation candidate or decision linked to a document anchor."""

    id: str = Field(default_factory=_new_id)
    project_id: str
    reference_id: Optional[str] = None
    citation_marker: Optional[str] = None
    anchor_id: Optional[str] = None
    paragraph_id: Optional[str] = None
    sentence_hash: Optional[str] = None
    surrounding_text_hash: Optional[str] = None
    cited_for: Optional[str] = None
    selected_reason: Optional[str] = None
    # candidate | approved | rejected | needs_repair | repaired | inserted | rendered | validated
    decision_state: str = "candidate"
    confidence: float = 0.0
    evidence_json: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
