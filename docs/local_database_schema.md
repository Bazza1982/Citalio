# Citalio — Local Database Schema Reference

Last updated: 2026-05-10
Status: **LOCKED** for Phase 0/1 hardening. No schema changes without a new migration and a review.

---

## Overview

Citalio uses a single SQLite database file (`citalio.db`) located inside the library root directory (`~/.citalio/` by default, or `$CITALIO_HOME`). The schema is managed by the migration runner in `citalio/db/connection.py`.

**Runtime PRAGMAs (enforced on every connection):**
- `PRAGMA journal_mode=WAL` — enables concurrent readers
- `PRAGMA busy_timeout=5000` — 5-second retry on SQLITE_BUSY
- `PRAGMA foreign_keys=ON` — enforced referential integrity

---

## Tables

### `schema_version`

Tracks applied migrations.

| Column | Type | Constraint | Notes |
|--------|------|------------|-------|
| `version` | INTEGER | PRIMARY KEY | Migration file prefix number (e.g. 1 for `001_initial_schema.sql`) |
| `applied_at` | TEXT | NOT NULL | ISO-8601 UTC timestamp of when the migration ran |
| `description` | TEXT | | Migration file stem (e.g. `001_initial_schema`) |

**Rules:** One row per applied migration. Never modified after insert. The runner checks this table at startup to determine pending migrations.

---

### `references`

The canonical citation library. One row per unique academic reference.

| Column | Type | Constraint | Notes |
|--------|------|------------|-------|
| `id` | TEXT | PRIMARY KEY | UUID v4 |
| `citekey` | TEXT | UNIQUE, nullable | BibTeX-style key (e.g. `smith2020deep`); NULL allowed |
| `item_type` | TEXT | NOT NULL | CSL type string: `article-journal`, `book`, `chapter`, `paper-conference`, `thesis`, `report`, `webpage`, `dataset`, `software`, `manuscript`, `pamphlet`, etc. |
| `title` | TEXT | NOT NULL | Full title; never empty |
| `year` | INTEGER | nullable | Publication year as 4-digit integer; NULL if unknown |
| `publication_title` | TEXT | nullable | Journal name, book title, series, etc. |
| `volume` | TEXT | nullable | Volume (stored as string to handle alphanumeric cases) |
| `issue` | TEXT | nullable | Issue / number |
| `pages` | TEXT | nullable | Page range string (e.g. `123--145`) |
| `publisher` | TEXT | nullable | |
| `place` | TEXT | nullable | Publisher city/country |
| `edition` | TEXT | nullable | |
| `doi` | TEXT | nullable | DOI without `https://doi.org/` prefix; **stored stripped of whitespace** |
| `isbn` | TEXT | nullable | |
| `issn` | TEXT | nullable | |
| `pmid` | TEXT | nullable | PubMed ID |
| `arxiv_id` | TEXT | nullable | arXiv identifier |
| `url` | TEXT | nullable | Landing-page URL |
| `abstract` | TEXT | nullable | Full abstract text |
| `language` | TEXT | nullable | BCP-47 language tag (e.g. `en`, `zh`) |
| `canonical_source` | TEXT | nullable | Import source string: `csl-json`, `bibtex`, `mcp`, `crossref`, etc. |
| `confidence_score` | REAL | DEFAULT 0.0 | Metadata confidence (0.0–1.0); set by connectors |
| `metadata_json` | TEXT | nullable | Arbitrary JSON blob for connector-specific fields |
| `created_at` | TEXT | NOT NULL | ISO-8601 UTC timestamp |
| `updated_at` | TEXT | NOT NULL | ISO-8601 UTC timestamp, updated on every mutation |

**Indexes:** `doi`, `title`, `year`, `citekey`

**Deduplication / merge rules:**
1. Match attempts (in order): exact `doi` → exact `citekey` → exact `title + year`
2. Conservative merge (`merge_policy='conservative'`, default): existing non-NULL fields are preserved; only NULL fields are filled by the incoming record. Empty incoming author list does NOT clear existing authors.
3. Overwrite merge (`merge_policy='overwrite'`): all fields (including authors) replaced by incoming values.

---

### `creators`

Shared creator (author/editor) registry. Creators are reused across references.

| Column | Type | Constraint | Notes |
|--------|------|------------|-------|
| `id` | TEXT | PRIMARY KEY | UUID v4 |
| `given` | TEXT | nullable | Given name(s) |
| `family` | TEXT | nullable | Family name |
| `literal` | TEXT | nullable | Full name string when family/given split unavailable |
| `orcid` | TEXT | nullable | ORCID identifier |
| `created_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL | |

**Deduplication rules (get_or_create_creator):**
1. Match by `orcid` first (if present)
2. Then exact `(family, given)` match
3. Then exact `literal` match
4. If no match: insert new row

Creators are **never deleted** when a reference is deleted or updated. They are shared entities; `reference_creators` is the join table.

---

### `reference_creators`

Many-to-many join between references and creators, with role and position.

| Column | Type | Constraint | Notes |
|--------|------|------------|-------|
| `reference_id` | TEXT | NOT NULL, FK→references | |
| `creator_id` | TEXT | NOT NULL, FK→creators | |
| `role` | TEXT | NOT NULL | `author` or `editor` |
| `position` | INTEGER | NOT NULL | 0-based order within the role |

**Primary key:** `(reference_id, role, position)`
**Unique constraint:** `(reference_id, role, creator_id)` — prevents duplicate links

**Mutation rule:** On upsert, all existing rows for the reference are deleted and re-inserted from the merged author/editor lists. This is done atomically in the same transaction as the reference UPDATE.

---

### `attachments`

File attachments linked to references (PDFs, supplementary files, etc.).

| Column | Type | Constraint | Notes |
|--------|------|------------|-------|
| `id` | TEXT | PRIMARY KEY | UUID v4 |
| `reference_id` | TEXT | NOT NULL, FK | |
| `kind` | TEXT | NOT NULL | `pdf`, `epub`, `html`, `supplementary`, `other` |
| `path` | TEXT | NOT NULL | File path — **must be relative to `library_root`** for portability |
| `mime_type` | TEXT | nullable | |
| `sha256` | TEXT | nullable | Hex digest for integrity verification |
| `source_url` | TEXT | nullable | Original download URL |
| `acquired_via` | TEXT | nullable | Connector name that acquired the file |
| `source_payload_json` | TEXT | nullable | Connector-specific acquisition metadata |
| `created_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL | |

**Path rule:** Paths stored here MUST be relative to the library root directory (e.g. `attachments/doi-10.1234-paper.pdf`), not absolute filesystem paths. This ensures library portability across machines.

---

### `chunks`

Full-text chunked excerpts for semantic indexing. Populated by `citalio embed index`.

| Column | Type | Constraint | Notes |
|--------|------|------------|-------|
| `id` | TEXT | PRIMARY KEY | UUID v4 |
| `reference_id` | TEXT | NOT NULL, FK | |
| `attachment_id` | TEXT | nullable, FK | If chunk comes from an attachment |
| `chunk_index` | INTEGER | NOT NULL | 0-based chunk order within the reference |
| `text` | TEXT | NOT NULL | Chunk text |
| `page_start` | INTEGER | nullable | |
| `page_end` | INTEGER | nullable | |
| `section` | TEXT | nullable | Section heading if known |
| `token_count` | INTEGER | nullable | Approximate token count |
| `embedding_id` | TEXT | nullable | Connector-specific vector ID for lookup |
| `metadata_json` | TEXT | nullable | |
| `created_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL | |

**Prototype note:** Chunk embeddings are stored externally (via connector). `embedding_id` references the connector's vector store. This table holds text and metadata; actual vectors are not stored in SQLite.

---

### `notes`

Researcher annotations on references.

| Column | Type | Constraint | Notes |
|--------|------|------------|-------|
| `id` | TEXT | PRIMARY KEY | UUID v4 |
| `reference_id` | TEXT | NOT NULL, FK | |
| `kind` | TEXT | NOT NULL | `user_note`, `ai_summary`, `relevance`, `extraction`, `tag` |
| `text` | TEXT | NOT NULL | Note body |
| `source` | TEXT | NOT NULL | Who created it: `user`, `mcp`, `llm`, connector name |
| `confidence` | REAL | DEFAULT 0.0 | For AI-generated notes; 0.0–1.0 |
| `metadata_json` | TEXT | nullable | |
| `created_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL | |

---

### `tags` and `reference_tags`

Flat tag taxonomy.

`tags`: `id` (UUID), `name` (TEXT UNIQUE NOT NULL)
`reference_tags`: `(reference_id, tag_id)` PRIMARY KEY, both FK-constrained

---

### `collections` and `collection_items`

Hierarchical collection tree.

`collections`: `id`, `parent_id` (nullable, self-FK), `name`, `description`, `created_at`, `updated_at`
`collection_items`: `(collection_id, reference_id)` PRIMARY KEY, optional `position` INTEGER

---

### `provenance_events`

Immutable audit trail of mutations and import events.

| Column | Type | Constraint | Notes |
|--------|------|------------|-------|
| `id` | TEXT | PRIMARY KEY | UUID v4 |
| `reference_id` | TEXT | nullable, FK | NULL allowed for system events not tied to a reference |
| `event_type` | TEXT | NOT NULL | `import`, `created`, `repaired`, `validated`, `downloaded`, `rendered`, `deleted` |
| `source` | TEXT | NOT NULL | Origin: `csl-json`, `bibtex`, `mcp`, `cli`, connector name |
| `source_record_id` | TEXT | nullable | Original ID in the source system |
| `before_json` | TEXT | nullable | Snapshot before mutation (for repair events) |
| `after_json` | TEXT | nullable | Snapshot after mutation |
| `confidence` | REAL | nullable | |
| `message` | TEXT | nullable | Human-readable description |
| `created_at` | TEXT | NOT NULL | |

**Rules:** Provenance rows are append-only; never updated or deleted.

---

### `citation_styles`

Registry of CSL citation styles.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `name` | TEXT NOT NULL | Display name (e.g. `APA 7th`) |
| `csl_path` | TEXT | Path to CSL XML file (relative to library root) |
| `locale` | TEXT | BCP-47 locale |
| `config_json` | TEXT | Connector-specific config |
| `created_at` | TEXT | |
| `updated_at` | TEXT | |

---

### `reference_render_cache`

Cached formatted citation strings per reference × style.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `reference_id` | TEXT NOT NULL FK | |
| `citation_style_id` | TEXT NOT NULL FK | |
| `inline_citation` | TEXT | Formatted inline string, e.g. `(Smith, 2020)` |
| `bibliography_entry` | TEXT | Full bibliography line |
| `rendered_at` | TEXT | ISO-8601 timestamp |
| `render_hash` | TEXT NOT NULL | Hash of the reference fields used; invalidate cache when hash changes |

**Invalidation rule:** When a reference's title, authors, year, or identifiers change, the `render_hash` will no longer match and the cache row should be deleted or re-rendered. The render cache is **not yet implemented** (Phase 0/1 scope); this table is reserved.

---

### `document_projects`

Document-level citation workflow projects.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUID v4 |
| `name` | TEXT NOT NULL | Human-readable project name |
| `root_path` | TEXT | Project directory (relative or absolute) |
| `docx_path` | TEXT | Path to the source Word document |
| `markdown_path` | TEXT | Path to the markdown draft |
| `sidecar_path` | TEXT | Path to the companion sidecar JSON file |
| `citation_style_id` | TEXT nullable FK | |
| `created_at` / `updated_at` | TEXT | |

---

### `document_anchors`

Citation locations in the document (paragraph / sentence positions).

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `project_id` | TEXT NOT NULL FK | |
| `paragraph_id` | TEXT | Paragraph identifier within document |
| `sentence_hash` | TEXT | Hash of the sentence text for drift detection |
| `surrounding_text_hash` | TEXT | Hash of surrounding context |
| `anchor_text` | TEXT | The citation placeholder text |
| `status` | TEXT NOT NULL DEFAULT `active` | `active`, `stale`, `resolved` |
| `created_at` / `updated_at` | TEXT | |

---

### `document_citation_decisions`

Approved/rejected citation choices for each anchor.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `project_id` | TEXT NOT NULL FK | |
| `reference_id` | TEXT nullable FK | NULL until a reference is linked |
| `citation_marker` | TEXT | The `[@citekey]` marker string |
| `anchor_id` | TEXT nullable FK | Link to the source anchor |
| `paragraph_id` / `sentence_hash` / `surrounding_text_hash` | TEXT | Denormalized for drift detection |
| `cited_for` | TEXT | Free-text reason this reference was selected |
| `selected_reason` | TEXT | Machine-readable selection rationale |
| `decision_state` | TEXT NOT NULL | `candidate`, `approved`, `rejected`, `inserted`, `rendered`, `validated`, `needs_repair` |
| `confidence` | REAL DEFAULT 0.0 | |
| `evidence_json` | TEXT | Structured evidence (similarity scores, passages, etc.) |
| `created_at` / `updated_at` | TEXT | |

**State machine:** `candidate` → `approved` or `rejected` → `inserted` (Step 8) → `rendered` (Step 9) → `validated` (Step 10). `needs_repair` is a re-entry state.

---

### `external_mappings`

Connector-specific identifier mappings (e.g. Zotero key, CrossRef ID).

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `reference_id` | TEXT NOT NULL FK | |
| `connector` | TEXT NOT NULL | Connector namespace: `zotero-citation-key`, `zotero-item-key`, `crossref`, `openalex`, etc. |
| `external_id` | TEXT NOT NULL | ID in the external system |
| `external_url` | TEXT | Landing URL |
| `payload_json` | TEXT | Full connector response payload |
| `created_at` / `updated_at` | TEXT | |

**Unique constraint:** `(connector, external_id)` — one mapping per connector per external ID.

**Zotero identity rule:** Citalio never uses Zotero keys as primary keys.
`references.id` remains the native Citalio UUID. Zotero citation keys and
internal item keys are stored here as separate connector namespaces so a future
sync or PDF acquisition step can refer back to Zotero without coupling Citalio's
core schema to Zotero.

---

## Migration Rules

1. Every schema change requires a new numbered migration SQL file in `citalio/db/migrations/`.
2. Each migration runs in an explicit `BEGIN EXCLUSIVE … COMMIT` transaction — partial DDL is not possible.
3. Migration files are append-only; never edit an already-applied migration.
4. The `schema_version` row is inserted at the END of each migration's transaction, so a failed migration leaves no version record.

---

## Concurrency Model

SQLite WAL mode allows one writer and many concurrent readers. The 5-second `busy_timeout` means write contention retries for up to 5 seconds before raising `SQLITE_BUSY`. The `CitationRepository` is designed for single-writer use; do not open two write-active connections to the same library simultaneously.
