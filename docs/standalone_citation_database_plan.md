# Citalio Standalone Citation Database Plan

## 1. Goal

Citalio should become a standalone PhD-scale citation and reference management system. It must not depend on Zotero software at runtime. Instead, Citalio owns a local citation database and treats Zotero as an optional compatibility adapter.

The product boundary is:

- Zotero manages personal reference libraries.
- Citalio manages citation decisions inside evolving research documents.
- Citalio can import from and export to Zotero-compatible formats, but Zotero is not the source of truth.

The first standalone package should support:

- Local structured citation database.
- PDF, markdown, note, chunk, and provenance storage.
- Semantic search over references and full text.
- Document-level citation decisions.
- Existing Citalio Word/Excel review workflow.
- Step 8 markdown citation insertion.
- Step 9 Word rendering with XML/run-level minimal patching.
- Step 10 final citation/reference validation.
- Librarian repair round trip.
- Incremental reference injection for updated drafts.
- Simple GUI for human users.
- MCP server so AI agents can operate Citalio directly.
- Optional connectors for Zotero, CrossRef, OpenAlex, Primo/library search, Ex-portario/EZproxy, and HASHI/LLM.

Versioning note: these features describe the intended standalone product, not the first release boundary. The v0.1 target is deliberately smaller and is defined in Section 19.

## 2. Architecture

```text
Citalio
├── Citalio Core
│   ├── document workflow
│   ├── sidecar state
│   ├── citation candidate review
│   ├── Step 8 markdown insertion
│   ├── Step 9 Word rendering
│   ├── Step 10 validation
│   ├── librarian repair
│   └── incremental update logic
│
├── Citalio Local Citation DB
│   ├── SQLite metadata store
│   ├── local attachment store
│   ├── notes and chunks
│   ├── semantic index
│   ├── provenance and repair history
│   ├── citation rendering cache
│   └── document decision links
│
├── Interfaces
│   ├── Python service API
│   ├── CLI
│   ├── GUI API
│   └── MCP server
│
└── Optional Connectors
    ├── Zotero import/export
    ├── CrossRef
    ├── OpenAlex
    ├── Primo/library search
    ├── Ex-portario/EZproxy downloader
    └── HASHI/LLM adapter
```

Core rule: Citalio Core talks to Citalio's repository interfaces, not directly to Zotero, CrossRef, OpenAlex, or an LLM.

## 3. Package Layout

Recommended Python package structure:

```text
citalio/
  __init__.py

  core/
    workflow.py
    projects.py
    sidecar.py
    decisions.py
    reconciliation.py
    incremental.py

  db/
    connection.py
    migrations/
      001_initial_schema.sql
    schema.py
    repository.py
    models.py
    identifiers.py
    merge.py
    provenance.py
    render_cache.py

  documents/
    docx_reader.py
    docx_patcher.py
    anchors.py
    markdown_insertion.py
    word_rendering.py

  review/
    excel_export.py
    excel_import.py
    candidate_sheet.py
    repair_sheet.py

  validation/
    citation_validator.py
    reference_validator.py
    consistency.py
    reports.py

  rendering/
    csl.py
    styles.py
    bibliography.py

  search/
    lexical.py
    chunks.py
    embeddings.py
    semantic_index.py

  connectors/
    base.py
    zotero.py
    crossref.py
    openalex.py
    primo.py
    ezproxy.py
    hashi.py

  gui/
    api.py
    app.py

  mcp/
    server.py
    tools.py
    resources.py

  cli/
    main.py
    commands_db.py
    commands_project.py
    commands_review.py
    commands_render.py
    commands_validate.py

  templates/
    excel/
    word/
    sidecar/

  schemas/
    sidecar.schema.json
    reference.schema.json
    decision.schema.json
    validation_report.schema.json
```

`db/migrations/` is not optional. Phase 1 must choose and implement one migration mechanism before Phase 2 data can be created:

- Preferred first implementation: a small custom migration runner using a `schema_version` table.
- Acceptable later replacement: Alembic, if migration complexity grows enough to justify the dependency.

The initial migration must be `001_initial_schema.sql` and must create `schema_version` before creating the rest of the schema.

## 4. Local Database Responsibilities

The local database is the canonical source of truth for Citalio references. It should store enough information to support both library management and document-aware citation decisions.

It should store:

- Bibliographic metadata.
- Authors, editors, translators, and other creators.
- Identifiers: DOI, ISBN, ISSN, PMID, arXiv, URL, library ID, Zotero key.
- Attachments: PDF, markdown, HTML, snapshots, extracted text.
- User notes and generated notes.
- Full-text chunks.
- Semantic search index references.
- Theory/contribution/cited_for summaries.
- Tags and collections.
- Provenance and repair history.
- Confidence scores.
- Citation style and render cache.
- Document projects and citation decisions.
- Links from document sentences/anchors to selected references.

The database should not store connector-specific data as top-level canonical fields unless that field is generally useful. Connector payloads belong in `metadata_json` or `source_payload_json`.

## 5. SQLite Schema Draft

### 5.0 schema version

```sql
CREATE TABLE schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  description TEXT
);
```

Rules:

- Every schema change ships as a numbered migration file in `db/migrations/`.
- Startup must check `schema_version` and apply pending migrations before opening repositories for writes.
- If a migration fails, Citalio must fail loudly and leave the DB in its previous transaction state.
- Phase 1 should start with a custom migration runner unless Alembic is deliberately chosen.

### 5.1 references

```sql
CREATE TABLE references (
  id TEXT PRIMARY KEY,
  citekey TEXT UNIQUE,
  item_type TEXT NOT NULL,
  title TEXT NOT NULL,
  year INTEGER,
  publication_title TEXT,
  volume TEXT,
  issue TEXT,
  pages TEXT,
  publisher TEXT,
  place TEXT,
  edition TEXT,
  doi TEXT,
  isbn TEXT,
  issn TEXT,
  pmid TEXT,
  arxiv_id TEXT,
  url TEXT,
  abstract TEXT,
  language TEXT,
  canonical_source TEXT,
  confidence_score REAL DEFAULT 0.0,
  metadata_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Indexes:

```sql
CREATE INDEX idx_references_doi ON references(doi);
CREATE INDEX idx_references_title ON references(title);
CREATE INDEX idx_references_year ON references(year);
CREATE INDEX idx_references_citekey ON references(citekey);
```

### 5.2 creators

```sql
CREATE TABLE creators (
  id TEXT PRIMARY KEY,
  given TEXT,
  family TEXT,
  literal TEXT,
  orcid TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE reference_creators (
  reference_id TEXT NOT NULL,
  creator_id TEXT NOT NULL,
  role TEXT NOT NULL,
  position INTEGER NOT NULL,
  PRIMARY KEY (reference_id, role, position),
  UNIQUE (reference_id, role, creator_id),
  FOREIGN KEY (reference_id) REFERENCES references(id),
  FOREIGN KEY (creator_id) REFERENCES creators(id)
);
```

Creator roles include `author`, `editor`, `translator`, `contributor`, and `organization`.

The primary key is intentionally `(reference_id, role, position)` so an author-order update changes the creator at a position instead of creating duplicate rows. The uniqueness rule still prevents the same creator from appearing twice in the same role. `merge.py` must handle author-order conflicts explicitly and record provenance before changing order.

### 5.3 attachments

```sql
CREATE TABLE attachments (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  mime_type TEXT,
  sha256 TEXT,
  source_url TEXT,
  acquired_via TEXT,
  source_payload_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (reference_id) REFERENCES references(id)
);
```

Attachment kinds:

- `pdf`
- `markdown`
- `html`
- `snapshot`
- `extracted_text`
- `supplement`

### 5.4 chunks

```sql
CREATE TABLE chunks (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL,
  attachment_id TEXT,
  chunk_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  page_start INTEGER,
  page_end INTEGER,
  section TEXT,
  token_count INTEGER,
  embedding_id TEXT,
  metadata_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (reference_id) REFERENCES references(id),
  FOREIGN KEY (attachment_id) REFERENCES attachments(id)
);
```

The embedding vector can live in a vector extension, sidecar index, or separate table. Keep `chunks.embedding_id` abstract so the DB works without embeddings.

### 5.5 notes and summaries

```sql
CREATE TABLE notes (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence REAL DEFAULT 0.0,
  metadata_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (reference_id) REFERENCES references(id)
);
```

Note kinds:

- `user_note`
- `summary`
- `theory`
- `contribution`
- `method`
- `evidence`
- `cited_for`
- `critique`
- `repair_note`

### 5.6 tags and collections

```sql
CREATE TABLE tags (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE reference_tags (
  reference_id TEXT NOT NULL,
  tag_id TEXT NOT NULL,
  PRIMARY KEY (reference_id, tag_id),
  FOREIGN KEY (reference_id) REFERENCES references(id),
  FOREIGN KEY (tag_id) REFERENCES tags(id)
);

CREATE TABLE collections (
  id TEXT PRIMARY KEY,
  parent_id TEXT,
  name TEXT NOT NULL,
  description TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (parent_id) REFERENCES collections(id)
);

CREATE TABLE collection_items (
  collection_id TEXT NOT NULL,
  reference_id TEXT NOT NULL,
  position INTEGER,
  PRIMARY KEY (collection_id, reference_id),
  FOREIGN KEY (collection_id) REFERENCES collections(id),
  FOREIGN KEY (reference_id) REFERENCES references(id)
);
```

### 5.7 provenance and repair history

```sql
CREATE TABLE provenance_events (
  id TEXT PRIMARY KEY,
  reference_id TEXT,
  event_type TEXT NOT NULL,
  source TEXT NOT NULL,
  source_record_id TEXT,
  before_json TEXT,
  after_json TEXT,
  confidence REAL,
  message TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (reference_id) REFERENCES references(id)
);
```

Event types:

- `created`
- `imported`
- `metadata_lookup`
- `merged`
- `deduplicated`
- `downloaded`
- `chunked`
- `embedded`
- `repaired`
- `validated`
- `exported`

### 5.8 citation styles and render cache

```sql
CREATE TABLE citation_styles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  csl_path TEXT,
  locale TEXT,
  config_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE reference_render_cache (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL,
  citation_style_id TEXT NOT NULL,
  inline_citation TEXT,
  bibliography_entry TEXT,
  rendered_at TEXT NOT NULL,
  render_hash TEXT NOT NULL,
  FOREIGN KEY (reference_id) REFERENCES references(id),
  FOREIGN KEY (citation_style_id) REFERENCES citation_styles(id)
);
```

Render cache invalidation:

- `render_hash` must be derived from canonical reference metadata, creator order, style ID/path, locale, and renderer version.
- Updating a reference, creator order, citation style, or renderer version invalidates affected cache rows.
- The first implementation can invalidate in application code; DB triggers are optional later if cache bugs appear.

### 5.9 document projects

```sql
CREATE TABLE document_projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  root_path TEXT,
  docx_path TEXT,
  markdown_path TEXT,
  sidecar_path TEXT,
  citation_style_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (citation_style_id) REFERENCES citation_styles(id)
);
```

### 5.10 document citation decisions

Document anchors are first-class records because incremental injection needs to detect drift over time.

```sql
CREATE TABLE document_anchors (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  paragraph_id TEXT,
  sentence_hash TEXT,
  surrounding_text_hash TEXT,
  anchor_text TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES document_projects(id)
);
```

Anchor statuses:

- `active`
- `stale`
- `resolved`

```sql
CREATE TABLE document_citation_decisions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  reference_id TEXT,
  citation_marker TEXT,
  anchor_id TEXT,
  paragraph_id TEXT,
  sentence_hash TEXT,
  surrounding_text_hash TEXT,
  cited_for TEXT,
  selected_reason TEXT,
  decision_state TEXT NOT NULL,
  confidence REAL DEFAULT 0.0,
  evidence_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES document_projects(id),
  FOREIGN KEY (anchor_id) REFERENCES document_anchors(id),
  FOREIGN KEY (reference_id) REFERENCES references(id)
);
```

Decision states:

- `candidate`
- `approved`
- `rejected`
- `needs_repair`
- `repaired`
- `inserted`
- `rendered`
- `validated`

### 5.11 connector mappings

```sql
CREATE TABLE external_mappings (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL,
  connector TEXT NOT NULL,
  external_id TEXT NOT NULL,
  external_url TEXT,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (connector, external_id),
  FOREIGN KEY (reference_id) REFERENCES references(id)
);
```

Examples:

- `connector = zotero`, `external_id = libraryID:itemKey`
- `connector = crossref`, `external_id = DOI`
- `connector = openalex`, `external_id = OpenAlex work ID`
- `connector = primo`, `external_id = institutional record ID`

## 6. File Storage Layout

Recommended local library layout:

```text
~/.citalio/
  citalio.db
  config.toml
  styles/
    apa.csl
    chicago.csl
  storage/
    references/
      ref_<id>/
        paper.pdf
        fulltext.md
        extracted.txt
        metadata.json
    projects/
      project_<id>/
        sidecar.json
        review.xlsx
        rendered.docx
        validation_report.json
  indexes/
    semantic/
    lexical/
  logs/
```

The DB should store relative paths where possible, so a library can be moved as a folder.

Path portability rule:

- `connection.py` records a single `library_root`.
- Paths stored in the DB should be relative to `library_root` unless an external absolute path is explicitly marked as external.
- Repository methods return resolved paths to callers but persist relative paths.

SQLite runtime settings:

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
conn.execute("PRAGMA foreign_keys=ON")
```

Concurrency model:

- Citalio supports many readers and one writer.
- CLI, GUI, and MCP may share a library, but write operations must be short transactions.
- Citalio does not promise safe multi-process concurrent writes to the same library beyond SQLite WAL and timeout behavior.

## 7. Repository Interfaces

The DB module should expose a stable service interface. Core workflows should depend on this interface, not raw SQL.

```python
class CitationRepository:
    def create_reference(self, record): ...
    def upsert_reference(self, record, merge_policy="conservative"): ...
    def get_reference(self, reference_id): ...
    def find_by_doi(self, doi): ...
    def find_by_citekey(self, citekey): ...
    def search_references(self, query, filters=None): ...
    def search_semantic(self, query, filters=None, limit=20): ...
    def add_attachment(self, reference_id, attachment): ...
    def add_note(self, reference_id, note): ...
    def add_chunks(self, reference_id, chunks): ...
    def record_provenance(self, event): ...
    def render_reference(self, reference_id, style_id): ...
    def export_references(self, format, reference_ids=None): ...
```

Document-aware methods:

```python
class DocumentCitationRepository:
    def create_project(self, project): ...
    def get_project(self, project_id): ...
    def import_sidecar(self, project_id, sidecar): ...
    def export_sidecar(self, project_id): ...
    def upsert_anchor(self, project_id, anchor): ...
    def mark_anchor_stale(self, anchor_id, reason): ...
    def list_candidates(self, project_id, anchor_id=None): ...
    def record_decision(self, decision): ...
    def approve_decision(self, decision_id): ...
    def reject_decision(self, decision_id, reason): ...
    def list_approved_for_rendering(self, project_id): ...
    def record_render_result(self, project_id, result): ...
    def record_validation_result(self, project_id, result): ...
```

Connector interface:

```python
class MetadataConnector:
    name: str

    def capabilities(self): ...

    def lookup_by_doi(self, doi): ...
    def search(self, query, limit=20): ...
    def normalize(self, payload): ...

class AcquisitionConnector:
    name: str

    def capabilities(self): ...

    def can_acquire(self, reference): ...
    def acquire(self, reference, destination_dir): ...

class LibraryImportExportConnector:
    name: str

    def capabilities(self): ...

    def import_records(self, source): ...
    def export_records(self, references, destination): ...
```

`connectors/base.py` should also define a shared `ConnectorError` base class. CLI and MCP code should report connector capability problems through structured errors rather than raw `ImportError` or backend-specific exceptions.

## 8. Zotero Compatibility Without Dependency

Citalio should support Zotero users through adapters and exchange formats.

Supported import/export targets:

- CSL JSON.
- BibTeX.
- BibLaTeX.
- RIS.
- Zotero RDF, optional later.
- Zotero local export folders, optional.
- Zotero Web API, optional.

Important rule: do not directly write to Zotero's SQLite database. Direct reads can be a power-user import option later, but it should never be the primary integration path.

Zotero-specific fields should be stored in `external_mappings` and connector payload JSON, not promoted into Citalio's canonical model unless they are generally useful.

## 9. Existing Citalio Workflow Integration

The current Citalio workflow described by Rain should be wrapped around the local database instead of rewritten immediately.

Before wrapping, Phase 0 must classify the current Veritas-backed Citalio implementation because several components are not portable shims. Known migration decisions:

| Existing component | Current coupling | Standalone Citalio target |
| --- | --- | --- |
| `Veritas/backend/app/services/citalio/citation_searcher.py` | Directly queries `VFProfileStore` / Qdrant and Veritas `cited_for` chunk shape | Replace with `search_semantic()` over local `chunks` plus optional semantic index. Qdrant is not a core dependency. |
| `relevance_scorer.py` | Inline LLM relevance scoring | Move behind optional HASHI/LLM connector, installed as `citalio[llm]`. Base Citalio must work with lexical/metadata scoring. |
| `citation_inserter.py` | Mostly workflow logic | Port directly into `documents/markdown_insertion.py` if inspection confirms no hard Veritas dependency. |
| `engine.py` | Orchestrates via Veritas internal modules such as `app.services.checker` | Decompose into `core/workflow.py` plus repository and connector calls. Do not import Veritas modules in standalone Citalio. |

Phase 0 deliverable: `docs/migration_inventory.md` must record every existing script/module, its dependency class, and its target package location. Phase 3/4 should not begin until this inventory identifies which code is direct-port, adapter-wrapped, or replaced.

### Step 8: Markdown insertion

Input:

- Approved citation decisions from sidecar and DB.
- Citation style.
- Target markdown draft.

Output:

- Updated markdown with citation markers.
- Decision states updated to `inserted`.
- Provenance event for each insertion.

Required behavior:

- Preserve existing citation markers.
- Add only missing approved citations.
- Keep idempotency: running Step 8 twice should not duplicate citations.

### Step 9: Word rendering

Input:

- Current Word document.
- Updated markdown or patch map.
- Approved citation decisions.
- Rendered inline citations and bibliography entries.

Output:

- Updated Word document.
- Render report.
- Decision states updated to `rendered`.

Guardrail:

Word rendering must preserve existing formatting through XML/run-level minimal patching. Do not rebuild paragraphs unless explicitly running a destructive repair mode.

Implementation strategy required before Phase 4:

- Write `docs/word_rendering_guardrails.md`.
- Define when `python-docx` Run APIs are acceptable and when direct `lxml` XML operations are required.
- Default to copy-on-write output such as `thesis.cited.docx`; never overwrite the source document by default.
- Define destructive repair mode separately, with explicit user confirmation and audit/provenance logging.
- Add at least one pytest fixture: input `.docx` plus patch map, then assert the output keeps existing run formatting around changed text.

Until those guardrails and fixtures exist, Step 9 remains a high-risk item and should not be treated as a v0.1 blocker.

### Step 10: Final validation

Input:

- Rendered Word document.
- Local citation DB.
- Project sidecar.
- Citation style.

Validation checks:

- Every in-text citation has a matching reference.
- Every inserted reference corresponds to an approved decision.
- Bibliography entries match rendered CSL output.
- No duplicate bibliography entries unless style requires them.
- DOI/title/year/author consistency.
- No rejected candidate was inserted.
- No approved candidate remains missing.

Output:

- Validation report.
- Repair sheet if problems exist.
- Provenance events.

### Librarian repair round trip

Input:

- Validation report.
- Repair Excel sheet.
- Local DB reference records.

Output:

- Corrected metadata.
- Corrected decisions.
- Updated confidence scores.
- Repair provenance events.

### Incremental reference injection

Input:

- Previous project state.
- Updated draft.
- Existing citation decisions.
- New or changed anchors.

Output:

- New candidate citations only for changed/missing areas.
- Existing approved citations preserved.
- Stale anchors marked for review.
- No full-document rebuild unless requested.

Anchor drift rule:

- If an anchor hash changes but surrounding context still matches, mark `document_anchors.status = 'stale'`.
- Existing decisions linked to stale anchors should move to `needs_repair` unless the validation layer can confidently re-resolve the anchor.
- Incremental injection tests must cover hash change, stale marking, and repair workflow.

## 10. GUI Scope

The first GUI should be simple and local. It should not try to replace the full Zotero UI.

Recommended GUI views:

1. Library
   - Search references.
   - Filter by tags, collections, year, author, source.
   - Open reference detail.

2. Reference Detail
   - Metadata.
   - Authors.
   - DOI/URL identifiers.
   - Attachments.
   - Notes and summaries.
   - Chunks/full text.
   - Provenance and repair history.

3. Project Dashboard
   - Linked document.
   - Sidecar status.
   - Citation decision counts.
   - Step 8/9/10 status.
   - Validation errors.

4. Candidate Review
   - Candidate citation.
   - Document context.
   - Suggested references.
   - cited_for/theory/contribution summary.
   - Approve/reject/repair controls.

5. Connector Settings
   - Zotero import/export path or API.
   - CrossRef/OpenAlex enablement.
   - Library/EZproxy settings.
   - LLM/HASHI settings.

Suggested implementation options:

- FastAPI backend plus local web UI.
- Tauri desktop wrapper later.
- Minimal first UI can be FastAPI + HTMX or FastAPI + React.

The GUI should call the same service layer as CLI and MCP.

## 11. MCP Server Scope

Citalio should expose an MCP server so AI agents can operate the citation DB and document workflow directly.

### MCP resources

```text
citalio://library/references
citalio://library/references/{reference_id}
citalio://library/references/{reference_id}/notes
citalio://library/references/{reference_id}/chunks
citalio://projects
citalio://projects/{project_id}
citalio://projects/{project_id}/decisions
citalio://projects/{project_id}/validation
```

### MCP tools

Library tools:

```text
citalio.search_references
citalio.get_reference
citalio.create_reference
citalio.update_reference
citalio.merge_references
citalio.add_attachment
citalio.add_note
citalio.import_references
citalio.export_references
```

Search tools:

```text
citalio.search_semantic
citalio.find_by_doi
citalio.find_similar_references
```

Optional connector tools:

```text
citalio.lookup_crossref
citalio.lookup_openalex
citalio.import_zotero
citalio.export_zotero
```

Optional acquisition tools requiring `citalio[library]`:

```text
citalio.acquire_pdf
```

If an optional connector or extra is unavailable, MCP must return a clear capability error that names the missing extra, for example `citalio[library]`, rather than exposing a Python import failure.

Project tools:

```text
citalio.create_project
citalio.load_project
citalio.import_sidecar
citalio.export_sidecar
citalio.list_candidates
citalio.approve_candidate
citalio.reject_candidate
citalio.repair_candidate
```

Workflow tools:

```text
citalio.run_step8_markdown_insertion
citalio.run_step9_word_rendering
citalio.run_step10_validation
citalio.generate_review_excel
citalio.apply_review_excel
citalio.run_incremental_injection
```

Safety rules for MCP:

- Tools that mutate documents must require explicit target paths.
- Word rendering must default to copy-on-write output.
- Destructive operations require `confirm=true`.
- Every mutation should write a provenance event.
- Agents should be able to inspect validation reports before applying repair.

## 12. CLI Scope

Suggested CLI:

```text
citalio init
citalio db status
citalio import zotero --file library.json
citalio import bibtex --file refs.bib
citalio export bibtex --out refs.bib
citalio refs search "institutional theory"
citalio refs show REF_ID
citalio refs attach REF_ID paper.pdf

citalio project create --docx thesis.docx --style apa
citalio project status PROJECT_ID
citalio review generate PROJECT_ID --out review.xlsx
citalio review apply PROJECT_ID review.xlsx
citalio render markdown PROJECT_ID
citalio render word PROJECT_ID --out thesis.cited.docx
citalio validate PROJECT_ID --docx thesis.cited.docx
citalio repair generate PROJECT_ID --out repair.xlsx
citalio repair apply PROJECT_ID repair.xlsx
citalio inject incremental PROJECT_ID --updated-docx thesis_v2.docx

citalio mcp serve
citalio gui serve
```

## 13. Migration Plan

### Phase 0: Inventory

Collect existing Citalio/Sakura Ref materials:

- Scripts.
- Prompt files.
- JSON schemas.
- Excel templates.
- Word rendering helpers.
- Sidecar examples.
- Validation reports.
- Test fixtures.
- Workflow docs.
- Veritas-backed Citalio modules and dependencies.

Classify each asset as:

- Keep as-is.
- Wrap behind CLI.
- Move into package.
- Replace with repository-backed implementation.
- Archive.

Required Phase 0 output:

- `docs/migration_inventory.md`.
- A component map for Veritas/Qdrant/HASHI-coupled code.
- A decision for every existing module: direct port, adapter wrapper, repository-backed rewrite, optional connector, or archive.
- Explicit replacement path for `citation_searcher.py`, `relevance_scorer.py`, `citation_inserter.py`, and `engine.py`.

### Phase 1: Package skeleton

Create the Python package, docs, test structure, and CLI entrypoint.

Deliverables:

- `citalio/` package.
- `docs/` architecture docs.
- `tests/`.
- `pyproject.toml`.
- `citalio init`.
- Migration runner with `schema_version`.
- `db/migrations/001_initial_schema.sql`.
- SQLite connection defaults: WAL, busy timeout, and foreign keys.
- Chosen CSL rendering strategy for the first implementation.

CSL decision for v0.1:

- Use a real renderer path rather than hand-written style formatting.
- Initial practical choice: evaluate and likely start with `citeproc-py` for basic APA/Chicago/Vancouver coverage.
- Full CSL compatibility is not a v0.1 promise; if `citeproc-py` proves insufficient, shelling out to `citeproc-js` can become a later optional renderer despite the Node runtime cost.

### Phase 2: Local DB MVP

Implement:

- SQLite connection and migrations.
- `references`, `creators`, `attachments`, `notes`, `provenance_events`.
- `schema_version`.
- Basic repository interface.
- CSL JSON import/export.
- BibTeX import/export.
- Tests for round-trip import/export.

Acceptance:

- A user can create a local Citalio library without Zotero.
- A user can import/export common citation formats.
- DOI/citekey/title lookup works.

### Phase 3: Document project and decision model

Implement:

- `document_projects`.
- `document_anchors`.
- `document_citation_decisions`.
- Sidecar import/export.
- Candidate decision CRUD.
- Excel review generation/parsing wrapper.

Acceptance:

- Existing review workflow can write decisions into local DB.
- Existing sidecar state can be imported and exported.

### Phase 4: Citalio Step 8/9/10 integration

Wrap or migrate:

- Step 8 markdown insertion.
- Step 9 Word rendering.
- Step 10 validation.

Acceptance:

- Rendering uses XML/run-level minimal patching.
- Validation detects missing and mismatched citations.
- Running the workflow twice is idempotent.
- Step 9 has guardrail documentation and formatting-preservation fixtures before implementation is considered complete.

### Phase 5: MCP server

Implement:

- Read resources.
- Search tools.
- Reference mutation tools.
- Project decision tools.
- Workflow tools.

Acceptance:

- An AI agent can search, inspect, approve, render, and validate through MCP.
- Mutating tools create provenance events.
- Word output remains copy-on-write by default.

### Phase 6: Simple GUI

Implement:

- Library search.
- Reference detail.
- Project dashboard.
- Candidate review.
- Validation report view.

Acceptance:

- A PhD user can manage references and review document citation decisions without touching CLI.

### Phase 7: Connectors

Implement as optional extras:

- Zotero import/export.
- CrossRef lookup.
- OpenAlex lookup.
- Primo/library search.
- Ex-portario/EZproxy acquisition.
- HASHI/LLM adapter.

Acceptance:

- Citalio works without connectors.
- Connectors improve acquisition and repair when configured.

## 14. Dependency Strategy

Base install should stay lightweight:

```text
citalio
  sqlite
  pydantic or dataclasses
  typer/click
  openpyxl
  python-docx/lxml
  citation import/export libs
  CSL renderer
```

Optional extras:

```text
citalio[gui]
citalio[mcp]
citalio[semantic]
citalio[zotero]
citalio[crossref]
citalio[openalex]
citalio[library]
citalio[llm]
citalio[all]
```

Heavy dependencies should be optional:

- Embedding models.
- Vector DB.
- Browser automation.
- PDF OCR.
- LLM clients.
- Library authentication/downloaders.

## 15. Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Zotero coupling leaks into core model | Citalio becomes adapter-shaped | Keep Zotero data in connector mappings and payload JSON |
| Word rendering rebuilds paragraphs | Formatting loss | Enforce XML/run-level minimal patching with tests |
| Metadata merge corrupts records | Wrong citations | Conservative merge policy, provenance, confidence |
| Duplicate references | Broken bibliography | DOI/citekey/title-author-year dedupe checks |
| Citation style mismatch | Invalid final document | Use CSL engine and render cache |
| CSL renderer selected too late | Phase 2 import/export and rendering assumptions drift | Lock v0.1 renderer strategy in Phase 1; mark full CSL compatibility as later scope |
| Semantic search unavailable | Reduced discovery | Make lexical search and metadata search mandatory; semantic optional |
| Veritas/Qdrant coupling blocks migration | Existing Citalio modules cannot be wrapped cleanly | Phase 0 migration inventory with explicit port/rewrite/connector decisions |
| LLM-generated summaries trusted too much | Bad cited_for/theory fields | Store source and confidence for every generated note |
| Incremental anchors drift | Missing or misplaced citations | Store anchor id, paragraph id, sentence hash, surrounding context |
| SQLite write contention | GUI, MCP, and CLI collide on writes | WAL mode, busy timeout, short transactions, single-writer model |
| Connector auth complexity | Fragile setup | Keep library/EZproxy connectors optional |
| GUI and MCP diverge | Inconsistent behavior | Both must call same service layer |
| Render cache becomes stale | Bibliography output mismatches updated metadata | Cache key must include a render hash derived from reference metadata, style, and locale; metadata updates invalidate affected cache entries |

## 16. Testing Strategy

Core DB tests:

- Create/update/reference round trip.
- Creator ordering.
- DOI lookup.
- Import/export CSL JSON.
- Import/export BibTeX.
- Provenance event creation.
- Attachment path portability.

Workflow tests:

- Sidecar import/export.
- Excel review round trip.
- Candidate approve/reject flow.
- Step 8 idempotency.
- Step 9 preserves Word formatting.
- Step 10 detects missing references.
- Librarian repair changes metadata and records provenance.
- Incremental injection preserves old decisions.
- Anchor drift: changed hash marks anchor stale and linked decisions `needs_repair`.
- Render cache invalidation after metadata or style changes.

Connector tests:

- Zotero import fixture.
- CSL JSON fixture.
- BibTeX fixture.
- CrossRef/OpenAlex mocked lookup.

MCP tests:

- Resources list expected DB/project state.
- Search tools return stable structured results.
- Mutating tools write provenance.
- Rendering tools are copy-on-write by default.

GUI tests:

- Library search loads.
- Reference detail loads.
- Project dashboard counts match DB.
- Candidate review writes decisions.

## 17. First Implementation Slice

Start with the smallest slice that proves independence from Zotero:

1. `citalio init` creates a local library.
2. User imports CSL JSON or BibTeX.
3. DB stores references, creators, attachments, notes, and provenance.
4. User searches references from CLI.
5. User creates a document project.
6. Existing sidecar decisions are imported.
7. Approved decisions can be listed and exported.

This establishes Citalio as standalone. Zotero compatibility can then be added as an adapter without changing the core.

## 18. Design Decisions To Lock Early

1. Database location:
   - Default `~/.citalio/citalio.db`.
   - Allow `CITALIO_HOME` and `--library`.

2. Reference IDs:
   - Use stable internal UUID/ULID.
   - Keep citekey editable and unique where possible.

3. Merge policy:
   - Conservative by default.
   - Never overwrite high-confidence fields with low-confidence connector data.

4. Word rendering:
   - Copy-on-write default.
   - Minimal XML/run patching mandatory.

5. Agent safety:
   - MCP mutation tools record provenance.
   - Destructive operations require explicit confirmation.

6. Connector status:
   - All external acquisition and lookup integrations are optional.

## 19. Definition of Done For v0.1

Citalio v0.1 is ready when:

- It can run without Zotero installed.
- It can create and manage a local citation DB.
- It can import/export at least CSL JSON and BibTeX.
- It can store PDFs or markdown attachments.
- It can store notes, chunks, provenance, and confidence.
- It can represent document projects and citation decisions.
- CLI works for core flows.
- Sidecar state can be imported/exported.
- Step 8 markdown insertion can consume approved decisions from the local DB.
- Basic validation can report missing references and mismatched approved/inserted decisions.

Deferred release boundaries:

| Version | Scope |
| --- | --- |
| v0.1 | DB + CLI + migrations + CSL JSON/BibTeX import-export + sidecar import-export + document projects/anchors/decisions + Step 8 + basic validation |
| v0.2 | MCP + Step 9 Word rendering + Step 10 full validation + Word formatting fixtures |
| v0.3 | GUI + incremental injection + optional connectors |

This keeps the first release focused on proving independence from Zotero. Word rendering, MCP, GUI, and acquisition connectors remain important product goals, but they should not block v0.1.

## 20. Review Fixes Incorporated

This plan incorporates Akane's 2026-05-09 architecture review:

- Added Phase 0 Veritas/Qdrant/HASHI migration inventory requirements.
- Reduced v0.1 scope and split later work into v0.2/v0.3.
- Added `schema_version`, migration runner requirements, and `001_initial_schema.sql`.
- Fixed `reference_creators` primary key and uniqueness rules.
- Added Phase 1 CSL renderer decision requirement.
- Added `document_anchors` and FK from decisions to anchors.
- Added Word rendering guardrail document and fixture requirement.
- Added SQLite WAL, busy timeout, foreign key, and single-writer concurrency rules.
- Moved `citalio.acquire_pdf` into optional `citalio[library]` MCP tooling.
- Added connector `capabilities()` and `ConnectorError` expectations.
- Added render-cache invalidation and anchor-drift tests.
