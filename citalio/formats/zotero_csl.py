"""Safe Zotero CSL-JSON metadata migration into Citalio.

This module only reads a user-supplied Zotero CSL-JSON export. It never reads
Zotero's SQLite database, never writes to Zotero, and never copies attachments.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from citalio.db.models import CreatorRecord, ProvenanceEvent, ReferenceRecord
from citalio.db.repository import CitationRepository
from citalio.formats.csl_json import _CSL_TO_ITEM_TYPE, _csl_year


DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)

ATTACHMENT_KEYS = {"attachment", "attachments", "file", "files"}


@dataclass
class MigrationCounts:
    source_records: int = 0
    new_records: int = 0
    merged_records: int = 0
    merged_by_doi: int = 0
    merged_by_title_year_exact: int = 0
    skipped_records: int = 0
    malformed_records: int = 0
    missing_doi: int = 0
    missing_year: int = 0
    missing_creators: int = 0
    organization_creators: int = 0
    attachment_fields_ignored: int = 0
    external_mappings_written: int = 0
    external_mappings_planned: int = 0


@dataclass
class MigrationWarning:
    code: str
    message: str
    record_id: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "record_id": self.record_id,
        }


@dataclass
class MigrationReport:
    source_file: str
    library_root: str
    mode: str
    started_at: str
    finished_at: str
    counts: MigrationCounts
    warnings: list[MigrationWarning] = field(default_factory=list)
    possible_duplicate_warnings: list[dict[str, Any]] = field(default_factory=list)
    report_path: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "library_root": self.library_root,
            "mode": self.mode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "counts": self.counts.__dict__,
            "warnings": [w.as_dict() for w in self.warnings],
            "possible_duplicate_warnings": self.possible_duplicate_warnings,
            "report_path": self.report_path,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_doi(raw: Any) -> tuple[Optional[str], Optional[str], bool]:
    """Return (normalized DOI, raw DOI string, had_unfamiliar_prefix_warning)."""
    if raw is None:
        return None, None, False

    raw_text = str(raw)
    value = raw_text.strip()
    lower = value.lower()
    for prefix in DOI_PREFIXES:
        if lower.startswith(prefix):
            return value[len(prefix):].strip(), raw_text, False

    if "doi.org/" in lower or lower.startswith("doi "):
        return value, raw_text, True
    return value, raw_text, False


def normalize_title_for_match(title: str) -> str:
    """Normalize title only for duplicate comparison; never store this value."""
    value = html.unescape(title or "")
    value = " ".join(value.strip().lower().split())
    return value.rstrip(".,:;")


def _csl_creators(csl_names: list[dict[str, Any]]) -> tuple[list[CreatorRecord], int]:
    creators: list[CreatorRecord] = []
    organization_count = 0
    for name in csl_names:
        if not isinstance(name, dict):
            continue
        literal = name.get("literal")
        if literal and not (name.get("family") or name.get("given")):
            organization_count += 1
        creators.append(
            CreatorRecord(
                given=name.get("given"),
                family=name.get("family"),
                literal=literal,
            )
        )
    return creators, organization_count


def _source_metadata(item: dict[str, Any], raw_doi: Optional[str]) -> str:
    metadata: dict[str, Any] = {}
    if raw_doi is not None:
        metadata["raw_doi"] = raw_doi
    known = {
        "id", "type", "title", "title-short", "DOI", "doi", "URL", "url",
        "container-title", "collection-title", "publisher", "publisher-place",
        "volume", "issue", "page", "edition", "ISBN", "ISSN", "PMID",
        "abstract", "language", "issued", "author", "editor",
    }
    extra = {k: v for k, v in item.items() if k not in known and k not in ATTACHMENT_KEYS}
    if extra:
        metadata["unmapped_csl"] = extra
    return json.dumps(metadata, ensure_ascii=False) if metadata else None


def csl_item_to_zotero_record(
    item: dict[str, Any],
) -> tuple[ReferenceRecord, list[MigrationWarning], int, bool]:
    """Convert one Zotero-exported CSL item to a Citalio reference record."""
    warnings: list[MigrationWarning] = []
    source_id = item.get("id")
    item_type = _CSL_TO_ITEM_TYPE.get(item.get("type", ""), item.get("type", "article"))
    title = item.get("title") or item.get("title-short") or "(no title)"

    doi, raw_doi, unfamiliar_doi = normalize_doi(item.get("DOI") or item.get("doi"))
    if unfamiliar_doi:
        warnings.append(
            MigrationWarning(
                code="unfamiliar_doi_format",
                message="DOI kept without inference because it used an unfamiliar form.",
                record_id=source_id,
            )
        )

    authors, author_orgs = _csl_creators(item.get("author", []))
    editors, editor_orgs = _csl_creators(item.get("editor", []))
    organization_count = author_orgs + editor_orgs
    has_attachment_fields = any(key in item for key in ATTACHMENT_KEYS)

    container = (
        item.get("container-title")
        or item.get("collection-title")
        or item.get("publisher")
    )

    record = ReferenceRecord(
        item_type=item_type,
        title=title,
        year=_csl_year(item.get("issued")),
        publication_title=container,
        volume=str(item["volume"]) if item.get("volume") else None,
        issue=str(item["issue"]) if item.get("issue") else None,
        pages=item.get("page"),
        publisher=item.get("publisher"),
        place=item.get("publisher-place"),
        edition=str(item["edition"]) if item.get("edition") else None,
        doi=doi,
        isbn=item.get("ISBN"),
        issn=item.get("ISSN"),
        pmid=item.get("PMID"),
        url=item.get("URL") or item.get("url"),
        abstract=item.get("abstract"),
        language=item.get("language"),
        canonical_source="zotero-csl-json",
        metadata_json=_source_metadata(item, raw_doi),
    )
    record = record.model_copy(update={"authors": authors, "editors": editors})
    return record, warnings, organization_count, has_attachment_fields


def _snapshot(record: Optional[ReferenceRecord]) -> Optional[str]:
    if record is None:
        return None
    return json.dumps(record.model_dump(mode="json"), ensure_ascii=False)


def _find_existing_for_migration(
    repo: CitationRepository, record: ReferenceRecord
) -> tuple[Optional[ReferenceRecord], Optional[str]]:
    if record.doi:
        existing = repo.find_by_doi(record.doi)
        if existing:
            return existing, "doi"
    target_title = normalize_title_for_match(record.title)
    if record.year is not None:
        for candidate in repo.list_references(limit=None):
            if (
                candidate.year == record.year
                and normalize_title_for_match(candidate.title) == target_title
            ):
                return candidate, "title_year_exact"
    return None, None


def _insert_external_mapping(
    conn: sqlite3.Connection,
    reference_id: str,
    external_id: str,
    source_file: str,
) -> bool:
    payload = json.dumps({"source": "zotero-csl-json", "source_file": source_file})
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO external_mappings (
            id, reference_id, connector, external_id, external_url,
            payload_json, created_at, updated_at
        ) VALUES (
            lower(hex(randomblob(16))), ?, 'zotero', ?, NULL, ?, datetime('now'), datetime('now')
        )
        """,
        (reference_id, external_id, payload),
    )
    conn.commit()
    return cur.rowcount > 0


def _write_report(report: MigrationReport, report_path: Path | None) -> None:
    if report_path is None:
        return
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report.report_path = str(report_path)
    report_path.write_text(
        json.dumps(report.as_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def import_zotero_csl_json(
    conn: sqlite3.Connection,
    path: Path | str,
    library_root: Path | str,
    *,
    dry_run: bool = False,
    report_path: Path | str | None = None,
    large_export_threshold: int = 500,
) -> MigrationReport:
    """Import a Zotero CSL-JSON metadata export, or dry-run it safely."""
    started_at = _now_iso()
    path = Path(path)
    library_root = Path(library_root)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Zotero CSL-JSON export must be a JSON array at the top level.")

    counts = MigrationCounts(source_records=len(data))
    warnings: list[MigrationWarning] = []
    if len(data) > large_export_threshold:
        warnings.append(
            MigrationWarning(
                code="large_export",
                message=(
                    f"{len(data)} records found; first-run test recommended "
                    f"with <{large_export_threshold} records."
                ),
            )
        )

    repo = CitationRepository(conn)

    for item in data:
        source_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(item, dict):
            counts.skipped_records += 1
            counts.malformed_records += 1
            warnings.append(
                MigrationWarning("malformed_item", "CSL item is not an object.", source_id)
            )
            continue

        try:
            record, item_warnings, org_count, has_attachment_fields = csl_item_to_zotero_record(item)
        except Exception as exc:
            counts.skipped_records += 1
            counts.malformed_records += 1
            warnings.append(
                MigrationWarning("malformed_item", f"Skipping malformed item: {exc}", source_id)
            )
            continue

        warnings.extend(item_warnings)
        counts.organization_creators += org_count
        if not record.doi:
            counts.missing_doi += 1
        if record.year is None:
            counts.missing_year += 1
        if not record.authors and not record.editors:
            counts.missing_creators += 1
        if has_attachment_fields:
            counts.attachment_fields_ignored += 1
            warnings.append(
                MigrationWarning(
                    "attachment_fields_ignored",
                    "Attachment/file fields were ignored during metadata-only migration.",
                    source_id,
                )
            )

        existing, merge_kind = _find_existing_for_migration(repo, record)
        if existing is None:
            counts.new_records += 1
        else:
            counts.merged_records += 1
            if merge_kind == "doi":
                counts.merged_by_doi += 1
            elif merge_kind == "title_year_exact":
                counts.merged_by_title_year_exact += 1
                record = record.model_copy(update={"title": existing.title})

        if source_id:
            counts.external_mappings_planned += 1

        if dry_run:
            continue

        ref_id = repo.upsert_reference(record)
        repo.record_provenance(
            ProvenanceEvent(
                reference_id=ref_id,
                event_type="import",
                source="zotero-csl-json",
                source_record_id=source_id,
                before_json=_snapshot(existing),
                after_json=json.dumps(item, ensure_ascii=False),
                message=f"DOI={record.doi or ''}, merge={'yes' if existing else 'no'}",
            )
        )
        if source_id and _insert_external_mapping(conn, ref_id, str(source_id), path.name):
            counts.external_mappings_written += 1

    finished_at = _now_iso()
    report = MigrationReport(
        source_file=str(path),
        library_root=str(library_root),
        mode="dry-run" if dry_run else "write",
        started_at=started_at,
        finished_at=finished_at,
        counts=counts,
        warnings=warnings,
    )

    final_report_path = Path(report_path) if report_path else (
        library_root / "migration_reports" / f"zotero_metadata_import_{started_at.replace(':', '-').replace('.', '-')}.json"
    )
    _write_report(report, final_report_path)
    return report
