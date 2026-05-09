-- Citalio initial schema
-- Migration 001
-- schema_version must be created first so the runner can record this migration.

CREATE TABLE IF NOT EXISTS schema_version (
  version     INTEGER PRIMARY KEY,
  applied_at  TEXT NOT NULL,
  description TEXT
);

-- -------------------------------------------------------------------------
-- references
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS "references" (
  id                TEXT PRIMARY KEY,
  citekey           TEXT UNIQUE,
  item_type         TEXT NOT NULL,
  title             TEXT NOT NULL,
  year              INTEGER,
  publication_title TEXT,
  volume            TEXT,
  issue             TEXT,
  pages             TEXT,
  publisher         TEXT,
  place             TEXT,
  edition           TEXT,
  doi               TEXT,
  isbn              TEXT,
  issn              TEXT,
  pmid              TEXT,
  arxiv_id          TEXT,
  url               TEXT,
  abstract          TEXT,
  language          TEXT,
  canonical_source  TEXT,
  confidence_score  REAL DEFAULT 0.0,
  metadata_json     TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_references_doi     ON "references"(doi);
CREATE INDEX IF NOT EXISTS idx_references_title   ON "references"(title);
CREATE INDEX IF NOT EXISTS idx_references_year    ON "references"(year);
CREATE INDEX IF NOT EXISTS idx_references_citekey ON "references"(citekey);

-- -------------------------------------------------------------------------
-- creators
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS creators (
  id         TEXT PRIMARY KEY,
  given      TEXT,
  family     TEXT,
  literal    TEXT,
  orcid      TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_creators (
  reference_id TEXT    NOT NULL,
  creator_id   TEXT    NOT NULL,
  role         TEXT    NOT NULL,
  position     INTEGER NOT NULL,
  PRIMARY KEY (reference_id, role, position),
  UNIQUE (reference_id, role, creator_id),
  FOREIGN KEY (reference_id) REFERENCES "references"(id),
  FOREIGN KEY (creator_id)   REFERENCES creators(id)
);

-- -------------------------------------------------------------------------
-- attachments
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS attachments (
  id                  TEXT PRIMARY KEY,
  reference_id        TEXT NOT NULL,
  kind                TEXT NOT NULL,
  path                TEXT NOT NULL,
  mime_type           TEXT,
  sha256              TEXT,
  source_url          TEXT,
  acquired_via        TEXT,
  source_payload_json TEXT,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  FOREIGN KEY (reference_id) REFERENCES "references"(id)
);

-- -------------------------------------------------------------------------
-- chunks
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS chunks (
  id            TEXT    PRIMARY KEY,
  reference_id  TEXT    NOT NULL,
  attachment_id TEXT,
  chunk_index   INTEGER NOT NULL,
  text          TEXT    NOT NULL,
  page_start    INTEGER,
  page_end      INTEGER,
  section       TEXT,
  token_count   INTEGER,
  embedding_id  TEXT,
  metadata_json TEXT,
  created_at    TEXT    NOT NULL,
  updated_at    TEXT    NOT NULL,
  FOREIGN KEY (reference_id)  REFERENCES "references"(id),
  FOREIGN KEY (attachment_id) REFERENCES attachments(id)
);

-- -------------------------------------------------------------------------
-- notes
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS notes (
  id            TEXT PRIMARY KEY,
  reference_id  TEXT NOT NULL,
  kind          TEXT NOT NULL,
  text          TEXT NOT NULL,
  source        TEXT NOT NULL,
  confidence    REAL DEFAULT 0.0,
  metadata_json TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  FOREIGN KEY (reference_id) REFERENCES "references"(id)
);

-- -------------------------------------------------------------------------
-- tags and collections
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tags (
  id   TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS reference_tags (
  reference_id TEXT NOT NULL,
  tag_id       TEXT NOT NULL,
  PRIMARY KEY (reference_id, tag_id),
  FOREIGN KEY (reference_id) REFERENCES "references"(id),
  FOREIGN KEY (tag_id)       REFERENCES tags(id)
);

CREATE TABLE IF NOT EXISTS collections (
  id          TEXT PRIMARY KEY,
  parent_id   TEXT,
  name        TEXT NOT NULL,
  description TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  FOREIGN KEY (parent_id) REFERENCES collections(id)
);

CREATE TABLE IF NOT EXISTS collection_items (
  collection_id TEXT    NOT NULL,
  reference_id  TEXT    NOT NULL,
  position      INTEGER,
  PRIMARY KEY (collection_id, reference_id),
  FOREIGN KEY (collection_id) REFERENCES collections(id),
  FOREIGN KEY (reference_id)  REFERENCES "references"(id)
);

-- -------------------------------------------------------------------------
-- provenance
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS provenance_events (
  id               TEXT PRIMARY KEY,
  reference_id     TEXT,
  event_type       TEXT NOT NULL,
  source           TEXT NOT NULL,
  source_record_id TEXT,
  before_json      TEXT,
  after_json       TEXT,
  confidence       REAL,
  message          TEXT,
  created_at       TEXT NOT NULL,
  FOREIGN KEY (reference_id) REFERENCES "references"(id)
);

-- -------------------------------------------------------------------------
-- citation styles and render cache
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS citation_styles (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  csl_path    TEXT,
  locale      TEXT,
  config_json TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_render_cache (
  id                 TEXT PRIMARY KEY,
  reference_id       TEXT NOT NULL,
  citation_style_id  TEXT NOT NULL,
  inline_citation    TEXT,
  bibliography_entry TEXT,
  rendered_at        TEXT NOT NULL,
  render_hash        TEXT NOT NULL,
  FOREIGN KEY (reference_id)      REFERENCES "references"(id),
  FOREIGN KEY (citation_style_id) REFERENCES citation_styles(id)
);

-- -------------------------------------------------------------------------
-- document projects
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS document_projects (
  id                TEXT PRIMARY KEY,
  name              TEXT NOT NULL,
  root_path         TEXT,
  docx_path         TEXT,
  markdown_path     TEXT,
  sidecar_path      TEXT,
  citation_style_id TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  FOREIGN KEY (citation_style_id) REFERENCES citation_styles(id)
);

-- -------------------------------------------------------------------------
-- document anchors and citation decisions
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS document_anchors (
  id                     TEXT PRIMARY KEY,
  project_id             TEXT NOT NULL,
  paragraph_id           TEXT,
  sentence_hash          TEXT,
  surrounding_text_hash  TEXT,
  anchor_text            TEXT,
  status                 TEXT NOT NULL DEFAULT 'active',
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES document_projects(id)
);

CREATE TABLE IF NOT EXISTS document_citation_decisions (
  id                     TEXT PRIMARY KEY,
  project_id             TEXT NOT NULL,
  reference_id           TEXT,
  citation_marker        TEXT,
  anchor_id              TEXT,
  paragraph_id           TEXT,
  sentence_hash          TEXT,
  surrounding_text_hash  TEXT,
  cited_for              TEXT,
  selected_reason        TEXT,
  decision_state         TEXT NOT NULL,
  confidence             REAL DEFAULT 0.0,
  evidence_json          TEXT,
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL,
  FOREIGN KEY (project_id)   REFERENCES document_projects(id),
  FOREIGN KEY (anchor_id)    REFERENCES document_anchors(id),
  FOREIGN KEY (reference_id) REFERENCES "references"(id)
);

-- -------------------------------------------------------------------------
-- connector mappings
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS external_mappings (
  id           TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL,
  connector    TEXT NOT NULL,
  external_id  TEXT NOT NULL,
  external_url TEXT,
  payload_json TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  UNIQUE (connector, external_id),
  FOREIGN KEY (reference_id) REFERENCES "references"(id)
);
