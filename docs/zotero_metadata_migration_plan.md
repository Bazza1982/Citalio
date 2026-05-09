# Zotero to Citalio Metadata-Only Migration Plan

Status: planning only; reviewed by akane on 2026-05-10
Last updated: 2026-05-10

This plan defines a safe first migration stream from Zotero into the Citalio
native reference database. The first run imports reference metadata only. It
does not copy PDFs, does not modify Zotero, and does not read Zotero's SQLite
database directly.

## Goal

Seed a Citalio native library with enough reference metadata to support search,
review, Step 8/9/10 planning, and later document citation workflows.

The first migration should answer:

- Can Citalio import the user's Zotero references into `citalio.db`?
- Are DOI/title/year/creator fields preserved correctly?
- How many duplicates or malformed records appear?
- Which fields need improved mapping before real workflow use?

## Non-Goals

The first test run must not:

- copy PDF attachments
- move, rename, or delete any Zotero files
- write to Zotero
- open or modify Zotero's `zotero.sqlite`
- depend on Zotero being installed at Citalio runtime
- create a live sync relationship
- run OCR, embeddings, semantic indexing, or full-text extraction
- expose imported data as a stable production workflow without review

## Safety Rules

1. **Export-only boundary**
   - The user exports data from Zotero using Zotero's normal export UI.
   - Citalio reads only the exported file.
   - Citalio never opens Zotero's live database.

2. **Metadata-only**
   - Export references using CSL JSON first.
   - Disable attachment/file export in Zotero.
   - If exported records contain attachment paths, Citalio records a warning and
     ignores them for this run.

3. **Separate Citalio test library**
   - Use a fresh Citalio library directory, for example:
     `~/citalio-test-library`
   - Do not import into the user's long-term library until the report is clean.

4. **Dry-run before write**
   - Add or use a dry-run import mode before the first real write.
   - Dry-run parses the export and produces a report without writing any
     reference data.
   - Dry-run may create/open the Citalio DB and apply migrations so the command
     can verify the real target library is usable. It must not write rows to
     `references`, `creators`, `reference_creators`, `provenance_events`,
     `external_mappings`, or attachment-related tables.

5. **Audit report required**
   - Every migration run must produce a report with counts and warnings.
   - The report must be kept beside the Citalio test library.

6. **No destructive operations**
   - No delete/truncate command should run as part of migration.
   - If a test library must be reset, do it by creating a new empty library
     directory, not by deleting records from Zotero or a production Citalio DB.

## Recommended User Export From Zotero

For the first run:

1. In Zotero, select the library or collection to test.
2. Export selected items.
3. Format: `CSL JSON`.
4. Notes: optional, but preferred off for first run unless needed.
5. Files/attachments: off.
6. Save as a clearly named file, for example:
   `zotero_export_metadata_only_2026-05-10.json`.

BibTeX can be tested second because it exercises citekeys, but CSL JSON should
be the first canonical test path.

## Citalio Import Flow

### Phase A — Preflight

Input:

- export file path
- Citalio library root
- import mode: `dry-run` or `write`

Checks:

- file exists
- file is valid JSON
- top-level value is a list
- library root is not inside Zotero's storage directory
- Citalio DB opens and migrations apply cleanly
- if record count is over 500, warn that the first test should use a smaller
  collection if possible

Output:

- preflight status
- number of raw exported items
- large-export warning, if applicable
- fatal parse errors, if any

Dry-run boundary:

- `--dry-run` may create the target DB file and schema.
- `--dry-run` must not write reference, creator, provenance, mapping, note,
  chunk, or attachment rows.
- Tests should assert that dry-run leaves `references` and related data tables
  empty, not that no DB file was created.

### Phase B — Parse and Normalize

For each CSL JSON item:

- normalize item type to Citalio `item_type`
- normalize DOI using the explicit rules below
- extract title
- extract issued year
- map `container-title` to `publication_title`
- preserve URL, abstract, volume, issue, pages, publisher, language
- map creators into `authors` and `editors`
- store unmapped Zotero/CSL fields in `metadata_json`
- always preserve source fields needed for recovery/debugging, including raw DOI
  if present

Malformed records should be skipped with a warning, not crash the whole import,
unless the JSON file itself is invalid.

#### DOI normalization rules

DOI normalization must be conservative and reversible.

For `references.doi`, apply only these transformations:

1. Strip leading/trailing whitespace.
2. Remove one known DOI prefix, case-insensitively, if present at the start:
   - `https://doi.org/`
   - `http://doi.org/`
   - `https://dx.doi.org/`
   - `http://dx.doi.org/`
   - `doi:`
3. Strip leading/trailing whitespace again.
4. Do not perform any other guessing, truncation, URL parsing, punctuation
   trimming, lowercasing, or character rewriting.

Always store the original source value in `metadata_json["raw_doi"]` when a DOI
field exists. If the DOI field has an unfamiliar form, preserve it as-is after
whitespace trimming and emit a warning instead of trying to infer a DOI.

#### Creator normalization rules

CSL JSON names map as follows:

- `author` entries become `CreatorRecord` rows linked as role `author`.
- `editor` entries become `CreatorRecord` rows linked as role `editor`.
- organization-style creators are stored as `CreatorRecord.literal` and linked
  as role `author` for the first migration.

The report must count organization creators separately so we can evaluate
whether later schema or role handling should be refined.

### Phase C — Duplicate Detection

Citalio's current merge order:

1. DOI
2. citekey
3. normalized title + year

For the migration report, track:

- new records
- merged records
- merged by DOI
- merged by normalized title + year
- records with no DOI
- title/year matches
- possible duplicates that were not merged

Possible duplicate warnings should include examples, but should not block the
test run.

Title normalization for duplicate comparison only:

- lowercase
- trim leading/trailing whitespace
- collapse repeated internal whitespace to one space
- remove trailing `.`, `,`, `:`, or `;`
- decode common JSON/HTML entities if they appear in exported title text

Do not modify the stored title value. Do not do stemming, fuzzy matching, or
article removal in the first migration. If records look similar but fail the
conservative normalized comparison, report them as possible duplicates rather
than merging them.

### Phase D — Write to Citalio

For each normalized item:

- call `CitationRepository.upsert_reference()`
- use conservative merge by default
- write provenance event:
  - `event_type`: `import`
  - `source`: `zotero-csl-json`
  - `source_record_id`: CSL JSON `id` if present
  - `before_json`: DB record snapshot before merge, or `null` for new records
  - `after_json`: raw CSL JSON item exactly as received
  - `message`: include DOI and whether the import merged with an existing record
- write `external_mappings` when CSL JSON `id` is present:
  - `connector`: `zotero`
  - `external_id`: CSL JSON `id`
  - `payload_json`: small source summary, not the full attachment payload

Attachments are ignored in this first run.

The raw CSL JSON item belongs in provenance `after_json`, not only in
`metadata_json`. `metadata_json` should keep field-level recovery data such as
`raw_doi` and unmapped CSL fields.

### Phase E — Report

Produce a migration report containing:

- source file
- library root
- dry-run vs write mode
- total source records
- imported records
- merged records
- skipped records
- malformed records
- records missing DOI
- records missing year
- records missing creators
- attachment fields ignored
- top warnings
- timestamp

Suggested path:

`<library_root>/migration_reports/zotero_metadata_import_<timestamp>.json`

A readable Markdown summary can be added later, but JSON is enough for the
first implementation.

Minimum JSON report shape:

```json
{
  "source_file": "/path/to/zotero_export.json",
  "library_root": "/home/lily/citalio-test-library",
  "mode": "dry-run",
  "started_at": "2026-05-10T00:00:00Z",
  "finished_at": "2026-05-10T00:00:03Z",
  "counts": {
    "source_records": 8342,
    "new_records": 8200,
    "merged_records": 120,
    "merged_by_doi": 90,
    "merged_by_title_year_exact": 30,
    "skipped_records": 22,
    "malformed_records": 22,
    "missing_doi": 2100,
    "missing_year": 180,
    "missing_creators": 64,
    "organization_creators": 39,
    "attachment_fields_ignored": 0,
    "external_mappings_written": 0
  },
  "warnings": [
    {
      "code": "large_export",
      "message": "8342 records found; first-run test recommended with <500 records.",
      "record_id": null
    }
  ],
  "possible_duplicate_warnings": [
    {
      "source_record_id": "ABCD1234",
      "candidate_reference_id": "uuid",
      "reason": "similar_normalized_title_same_year"
    }
  ]
}
```

In write mode, `external_mappings_written` should count Zotero item keys written
to `external_mappings`. In dry-run mode it should remain zero, but the report
may include `external_mappings_planned` if useful.

## Minimum Acceptance Criteria

The first migration stream is complete when:

- A metadata-only CSL JSON import can run in dry-run mode.
- A metadata-only CSL JSON import can write to a fresh Citalio test library.
- No PDFs or attachment files are copied.
- No Zotero database or storage files are modified.
- DOI/title/year/publication/creator fields survive import.
- Duplicate handling uses existing repository merge behavior.
- DOI normalization follows the explicit prefix-only rules and stores
  `metadata_json["raw_doi"]`.
- Duplicate reporting distinguishes DOI merges from normalized title/year merges.
- Provenance stores DB `before_json` and raw CSL JSON `after_json`.
- Zotero item keys are written to `external_mappings` in write mode.
- A migration report is produced.
- Tests cover:
  - valid CSL JSON import
  - malformed CSL JSON item skip
  - dry-run writes no reference/creator/provenance/mapping rows
  - write mode creates references
  - attachment fields are ignored with warnings
  - provenance is recorded
  - duplicate DOI merges rather than duplicates
  - raw DOI is preserved and normalized DOI is written
  - organization creators map to literal author creators
  - large export warning threshold

## Suggested Branch

Use a focused branch:

```bash
git checkout -b feature/zotero-metadata-migration
```

## Suggested CLI Shape

Keep the command explicit and cautious:

```bash
citalio import zotero-csl-json \
  --file zotero_export_metadata_only_2026-05-10.json \
  --library ~/citalio-test-library \
  --dry-run
```

Then:

```bash
citalio import zotero-csl-json \
  --file zotero_export_metadata_only_2026-05-10.json \
  --library ~/citalio-test-library
```

The existing generic CSL JSON importer can remain, but the Zotero-specific
command should add safety checks, attachment ignoring, source tagging, and a
migration report.

## Implementation Notes

- Prefer building this as a thin wrapper around existing CSL JSON import logic.
- Do not introduce a Zotero Python dependency.
- Do not call Zotero APIs in the first stream.
- Keep all Zotero-specific assumptions in `citalio/formats/` or a future
  `citalio/connectors/zotero/` boundary.
- If a field is ambiguous, preserve it in `metadata_json` and report it.
- Treat this as a test migration until the report has been reviewed.
