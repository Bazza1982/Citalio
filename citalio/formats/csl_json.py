"""CSL-JSON import and export for Citalio."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from citalio.db.models import CreatorRecord, ProvenanceEvent, ReferenceRecord
from citalio.db.repository import CitationRepository


# CSL type → internal item_type passthrough (CSL types are already fine)
_CSL_TO_ITEM_TYPE: dict[str, str] = {
    "article-journal": "article-journal",
    "article": "article",
    "article-magazine": "article-magazine",
    "article-newspaper": "article-newspaper",
    "book": "book",
    "chapter": "chapter",
    "paper-conference": "paper-conference",
    "thesis": "thesis",
    "report": "report",
    "webpage": "webpage",
    "dataset": "dataset",
    "software": "software",
    "patent": "patent",
    "manuscript": "manuscript",
    "broadcast": "broadcast",
    "speech": "speech",
    "interview": "interview",
    "map": "map",
    "motion_picture": "motion_picture",
    "musical_score": "musical_score",
    "pamphlet": "pamphlet",
    "personal_communication": "personal_communication",
    "post": "post",
    "post-weblog": "post-weblog",
    "review": "review",
    "review-book": "review-book",
    "treaty": "treaty",
}


def _csl_year(issued: Any) -> Optional[int]:
    """Extract a year integer from a CSL 'issued' date-variable."""
    if not issued:
        return None
    parts = issued.get("date-parts", [])
    if parts and parts[0]:
        try:
            return int(parts[0][0])
        except (TypeError, ValueError):
            return None
    raw = issued.get("raw", "")
    if raw:
        try:
            return int(str(raw)[:4])
        except ValueError:
            return None
    return None


def _csl_creators(csl_names: list[dict]) -> list[CreatorRecord]:
    creators = []
    for name in csl_names:
        creators.append(
            CreatorRecord(
                given=name.get("given"),
                family=name.get("family"),
                literal=name.get("literal"),
            )
        )
    return creators


def _csl_item_to_record(item: dict[str, Any]) -> ReferenceRecord:
    """Convert one CSL-JSON item dict to a ReferenceRecord."""
    item_type = _CSL_TO_ITEM_TYPE.get(item.get("type", ""), item.get("type", "article"))
    title = item.get("title") or item.get("title-short") or "(no title)"

    doi = item.get("DOI") or item.get("doi")
    url = item.get("URL") or item.get("url")

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
        url=url,
        abstract=item.get("abstract"),
        language=item.get("language"),
        canonical_source="csl-json",
    )
    record = record.model_copy(
        update={
            "authors": _csl_creators(item.get("author", [])),
            "editors": _csl_creators(item.get("editor", [])),
        }
    )
    return record


def import_csl_json(conn: sqlite3.Connection, path: Path | str) -> int:
    """Import a CSL-JSON file (array of items) into the database.

    Returns the number of references successfully imported.
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("CSL-JSON file must be a JSON array at the top level.")

    repo = CitationRepository(conn)
    count = 0
    for item in data:
        try:
            record = _csl_item_to_record(item)
            ref_id = repo.upsert_reference(record)
            repo.record_provenance(
                ProvenanceEvent(
                    reference_id=ref_id,
                    event_type="import",
                    source="csl-json",
                    source_record_id=item.get("id"),
                    message=f"Imported from {path.name}",
                )
            )
            count += 1
        except Exception as exc:
            # Skip malformed items but don't abort the whole import
            import warnings
            warnings.warn(f"Skipping CSL-JSON item due to error: {exc}")

    return count


def _record_to_csl_item(record: ReferenceRecord) -> dict[str, Any]:
    """Convert a ReferenceRecord back to a CSL-JSON dict."""
    item: dict[str, Any] = {"type": record.item_type, "title": record.title}

    if record.id:
        item["id"] = record.id
    if record.citekey:
        item["citation-key"] = record.citekey
    if record.doi:
        item["DOI"] = record.doi
    if record.url:
        item["URL"] = record.url
    if record.abstract:
        item["abstract"] = record.abstract
    if record.publication_title:
        item["container-title"] = record.publication_title
    if record.volume:
        item["volume"] = record.volume
    if record.issue:
        item["issue"] = record.issue
    if record.pages:
        item["page"] = record.pages
    if record.publisher:
        item["publisher"] = record.publisher
    if record.place:
        item["publisher-place"] = record.place
    if record.edition:
        item["edition"] = record.edition
    if record.isbn:
        item["ISBN"] = record.isbn
    if record.issn:
        item["ISSN"] = record.issn
    if record.language:
        item["language"] = record.language
    if record.year:
        item["issued"] = {"date-parts": [[record.year]]}

    if record.authors:
        item["author"] = [
            {k: v for k, v in {"given": a.given, "family": a.family, "literal": a.literal}.items() if v}
            for a in record.authors
        ]
    if record.editors:
        item["editor"] = [
            {k: v for k, v in {"given": e.given, "family": e.family, "literal": e.literal}.items() if v}
            for e in record.editors
        ]

    return item


def export_csl_json(
    conn: sqlite3.Connection,
    path: Path | str,
    reference_ids: Optional[list[str]] = None,
) -> int:
    """Export references to a CSL-JSON file.

    If reference_ids is None, exports all references.
    Returns the number of references exported.
    """
    repo = CitationRepository(conn)
    path = Path(path)

    if reference_ids is not None:
        records = [repo.get_reference(rid) for rid in reference_ids]
        records = [r for r in records if r is not None]
    else:
        rows = conn.execute('SELECT id FROM "references" ORDER BY year DESC, title ASC').fetchall()
        records = [repo.get_reference(row["id"]) for row in rows]
        records = [r for r in records if r is not None]

    items = [_record_to_csl_item(r) for r in records]
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(items)
