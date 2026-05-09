"""Validation report models for Citalio Step 10."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ValidationIssue:
    issue_type: str
    description: str
    decision_id: Optional[str] = None
    reference_id: Optional[str] = None
    marker: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type,
            "description": self.description,
            "decision_id": self.decision_id,
            "reference_id": self.reference_id,
            "marker": self.marker,
        }


@dataclass
class ValidationReport:
    project_id: str
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.issues) == 0

    def summary(self) -> str:
        if self.is_valid:
            return "Validation passed — no issues found."
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.issue_type] = counts.get(issue.issue_type, 0) + 1
        parts = [f"{v} {k}" for k, v in sorted(counts.items())]
        return f"Validation failed — {len(self.issues)} issue(s): " + ", ".join(parts)

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "generated_at": self.generated_at,
            "is_valid": self.is_valid,
            "issue_count": len(self.issues),
            "issues": [i.to_dict() for i in self.issues],
        }

    def write_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
