"""BibTeX import and export for Citalio using bibtexparser."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from citalio.db.models import CreatorRecord, ProvenanceEvent, ReferenceRecord
from citalio.db.repository import CitationRepository


# bibtex entry type → internal item_type
_BIBTEX_TO_ITEM_TYPE: dict[str, str] = {
    "article": "article-journal",
    "book": "book",
    "inbook": "chapter",
    "incollection": "chapter",
    "inproceedings": "paper-conference",
    "conference": "paper-conference",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "techreport": "report",
    "misc": "article",
    "unpublished": "manuscript",
    "booklet": "pamphlet",
    "manual": "report",
    "proceedings": "book",
}

_ITEM_TYPE_TO_BIBTEX: dict[str, str] = {
    "article-journal": "article",
    "article": "misc",
    "book": "book",
    "chapter": "incollection",
    "paper-conference": "inproceedings",
    "thesis": "phdthesis",
    "report": "techreport",
    "manuscript": "unpublished",
    "pamphlet": "booklet",
    "webpage": "misc",
    "dataset": "misc",
    "software": "misc",
}


def _parse_bibtex_authors(author_str: str) -> list[CreatorRecord]:
    """Parse a BibTeX author string into CreatorRecords."""
    if not author_str:
        return []
    creators = []
    for part in author_str.split(" and "):
        part = part.strip()
        if not part:
            continue
        if "," in part:
            # Family, Given
            family, _, given = part.partition(",")
            creators.append(CreatorRecord(family=family.strip(), given=given.strip()))
        elif " " in part:
            # Given Family (last token is family)
            tokens = part.split()
            creators.append(CreatorRecord(given=" ".join(tokens[:-1]), family=tokens[-1]))
        else:
            creators.append(CreatorRecord(literal=part))
    return creators


def _bibtex_entry_to_record(entry: Any) -> ReferenceRecord:
    """Convert a bibtexparser Entry to a ReferenceRecord."""
    # Support both bibtexparser v1 (dict-like) and v2 (field objects)
    try:
        # bibtexparser v2 style
        fields: dict[str, str] = {f.key: str(f.value) for f in entry.fields}
        entry_type = entry.type.lower()
        citekey = entry.key
    except AttributeError:
        # bibtexparser v1 style
        fields = dict(entry)
        entry_type = fields.pop("ENTRYTYPE", "misc").lower()
        citekey = fields.pop("ID", None)

    item_type = _BIBTEX_TO_ITEM_TYPE.get(entry_type, "article")

    title = fields.get("title", "(no title)").strip("{}")
    year_str = fields.get("year", "")
    year: Optional[int] = None
    if year_str:
        try:
            year = int(year_str[:4])
        except (ValueError, TypeError):
            pass

    doi = fields.get("doi") or fields.get("DOI")
    url = fields.get("url") or fields.get("URL")

    publication_title = (
        fields.get("journal")
        or fields.get("booktitle")
        or fields.get("series")
        or fields.get("publisher")
    )

    author_str = fields.get("author", "")
    editor_str = fields.get("editor", "")

    record = ReferenceRecord(
        citekey=citekey,
        item_type=item_type,
        title=title,
        year=year,
        publication_title=publication_title,
        volume=fields.get("volume"),
        issue=fields.get("number"),
        pages=fields.get("pages"),
        publisher=fields.get("publisher"),
        place=fields.get("address"),
        edition=fields.get("edition"),
        doi=doi,
        isbn=fields.get("isbn"),
        issn=fields.get("issn"),
        url=url,
        abstract=fields.get("abstract"),
        language=fields.get("language"),
        canonical_source="bibtex",
    )
    record = record.model_copy(
        update={
            "authors": _parse_bibtex_authors(author_str),
            "editors": _parse_bibtex_authors(editor_str),
        }
    )
    return record


def import_bibtex(conn: sqlite3.Connection, path: Path | str) -> int:
    """Import a .bib file into the database.

    Returns the count of imported references.
    """
    try:
        import bibtexparser
    except ImportError as exc:
        raise ImportError(
            "bibtexparser is required for BibTeX import. "
            "Install it with: pip install bibtexparser"
        ) from exc

    path = Path(path)
    bib_str = path.read_text(encoding="utf-8")

    # Try v2 API first, fall back to v1
    entries = _load_bibtex_entries(bibtexparser, bib_str)

    repo = CitationRepository(conn)
    count = 0
    for entry in entries:
        try:
            record = _bibtex_entry_to_record(entry)
            ref_id = repo.upsert_reference(record)
            repo.record_provenance(
                ProvenanceEvent(
                    reference_id=ref_id,
                    event_type="import",
                    source="bibtex",
                    source_record_id=getattr(entry, "key", None)
                    or (entry.get("ID") if hasattr(entry, "get") else None),
                    message=f"Imported from {path.name}",
                )
            )
            count += 1
        except Exception as exc:
            import warnings
            warnings.warn(f"Skipping BibTeX entry due to error: {exc}")

    return count


def _load_bibtex_entries(bibtexparser: Any, bib_str: str) -> list[Any]:
    """Load entries from bib string, supporting bibtexparser v1 and v2."""
    # Try v2 API
    if hasattr(bibtexparser, "parse_string"):
        try:
            lib = bibtexparser.parse_string(bib_str)
            return list(lib.entries)
        except Exception:
            pass

    # v1 API
    if hasattr(bibtexparser, "loads"):
        bib_db = bibtexparser.loads(bib_str)
        return bib_db.entries

    raise RuntimeError("Unrecognised bibtexparser API version.")


def _record_to_bibtex_entry(record: ReferenceRecord) -> str:
    """Convert a ReferenceRecord to a BibTeX entry string."""
    entry_type = _ITEM_TYPE_TO_BIBTEX.get(record.item_type, "misc")

    # Build citekey: fallback to first-author-year if no citekey stored
    if record.citekey:
        citekey = record.citekey
    elif record.authors:
        first = record.authors[0]
        family = (first.family or first.literal or "Unknown").split()[-1]
        citekey = f"{family}{record.year or 'nd'}"
    else:
        citekey = record.id[:8]

    fields: list[tuple[str, str]] = []

    def _add(key: str, val: Optional[str]) -> None:
        if val:
            # Wrap value in braces to protect case
            fields.append((key, f"{{{val}}}"))

    _add("title", record.title)

    if record.authors:
        author_str = " and ".join(_creator_to_bibtex(a) for a in record.authors)
        fields.append(("author", f"{{{author_str}}}"))

    if record.editors:
        editor_str = " and ".join(_creator_to_bibtex(e) for e in record.editors)
        fields.append(("editor", f"{{{editor_str}}}"))

    if record.year:
        fields.append(("year", str(record.year)))

    _add("journal" if entry_type == "article" else "booktitle", record.publication_title)
    _add("volume", record.volume)
    _add("number", record.issue)
    _add("pages", record.pages)
    _add("publisher", record.publisher)
    _add("address", record.place)
    _add("edition", record.edition)
    _add("doi", record.doi)
    _add("isbn", record.isbn)
    _add("issn", record.issn)
    _add("url", record.url)
    _add("abstract", record.abstract)
    _add("language", record.language)

    lines = [f"@{entry_type}{{{citekey},"]
    for key, val in fields:
        lines.append(f"  {key} = {val},")
    lines.append("}")
    return "\n".join(lines)


def _creator_to_bibtex(creator: CreatorRecord) -> str:
    if creator.literal:
        return creator.literal
    if creator.family and creator.given:
        return f"{creator.family}, {creator.given}"
    if creator.family:
        return creator.family
    return creator.given or ""


def export_bibtex(
    conn: sqlite3.Connection,
    path: Path | str,
    reference_ids: Optional[list[str]] = None,
) -> int:
    """Export references to a .bib file.

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

    entries = [_record_to_bibtex_entry(r) for r in records]
    path.write_text("\n\n".join(entries) + "\n", encoding="utf-8")
    return len(entries)
