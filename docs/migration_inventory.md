# Citalio Migration Inventory

Generated: 2026-05-09  
Scope: Veritas-backed Citalio modules at `/home/lily/projects/Veritas/backend/app/services/citalio/`  
(A replica exists under `scholarly-hollows/services/citalio/` — same files, same classification.)

---

## Summary

| Module | Classification | Target Location |
|--------|---------------|-----------------|
| `citation_searcher.py` | Repository-backed rewrite | `citalio/search/lexical.py` + `citalio/db/repository.py` |
| `relevance_scorer.py` | Optional connector (adapter port) | `citalio/connectors/hashi.py` via `citalio[llm]` |
| `citation_inserter.py` | Direct port | `citalio/documents/markdown_insertion.py` |
| `engine.py` | Decompose/rewrite | `citalio/core/workflow.py` + repository + connector calls |
| `manual_search.py` | Inspect before porting | `citalio/search/lexical.py` or CLI command |
| `__init__.py` | Archive (empty re-export shim) | Not ported |

---

## Detailed Classification

### `citation_searcher.py`

**Current coupling:**  
- Directly instantiates `VFProfileStore` from `app.services.vf_middleware.profile_store`  
- Calls `store.semantic_search(sentence_text, limit, chunk_id)` — a Veritas/Qdrant-backed search over VF chunk shapes (`cited_for`, `theory`, `contributions`)  
- Data model: `CitationCandidate` dataclass — **portable**, no Veritas imports

**Classification:** Repository-backed rewrite

**Target:** The `CitationCandidate` dataclass can be ported directly into `citalio/db/models.py`.  
The `CitationSearcher` class must be replaced with `CitationRepository.search_references()` (lexical) and `CitationRepository.search_semantic()` (optional, behind `citalio[semantic]`).  
Qdrant is not a runtime dependency. The `cited_for` / `theory` / `contributions` chunk shape maps to the `notes` table (kinds: `cited_for`, `theory`, `contribution`) and `chunks` table.

**Blocker:** Semantic search requires a local embedding index. Phase 2 can ship with lexical-only search; `citalio[semantic]` extends it.

---

### `relevance_scorer.py`

**Current coupling:**  
- Receives an `LLMCallFn` (async callable) injected by the engine — no hard Veritas import in this file itself  
- Uses only `CitationCandidate` (portable dataclass) and standard library  
- Depends on an LLM call for scoring; without it, falls back to vector relevance score

**Classification:** Optional connector (adapter port)

**Target:** The scoring logic is clean and portable. Port the class into `citalio/connectors/hashi.py` (or `citalio/connectors/llm.py`) as part of the optional `citalio[llm]` extra.  
Base Citalio must work with metadata-only or lexical scoring. When `citalio[llm]` is installed, the connector wires an LLM call into the scoring pipeline.  
`LLMCallFn` type alias should live in `citalio/connectors/base.py`.

**Blocker:** None for Phase 1. LLM connector is Phase 7 scope.

---

### `citation_inserter.py`

**Current coupling:**  
- Imports only `CitationCandidate` from the same package (portable)  
- Pure string manipulation logic — no Veritas, no DB, no LLM

**Classification:** Direct port

**Target:** `citalio/documents/markdown_insertion.py`  
The `CitationInserter.insert()` method can be ported as-is (or as a module-level function). It appends author-year citation markers to a sentence and belongs in the document insertion layer.  
The method is already idempotent for a single pass — Step 8 idempotency across multiple runs needs a surrounding check (see plan Section 9 Step 8).

**Blocker:** None. Can be ported in Phase 1 or Phase 4.

---

### `engine.py`

**Current coupling:**  
- `from app.services.checker import classifier, extractor, splitter` — Veritas sentence splitting and claim extraction  
- `from app.services.checker.engine import _default_llm_call` — Veritas LLM router  
- `from app.services.checker.rag_searcher import SentenceRAGResults` — Veritas RAG result shape  
- Orchestrates: split → extract → classify → search → score → insert

**Classification:** Decompose/rewrite into `citalio/core/workflow.py`

**Target:**  
- Sentence splitting → replace with `citalio/core/workflow.py` calling a pluggable splitter (stdlib `re`-based for MVP, optional `spacy` later)  
- Claim extraction → deferred; MVP can skip automated extraction and work from explicit user decisions  
- Classification (CITE_NEEDED vs COMMON) → deferred; Step 8 consumes pre-approved decisions from the DB, so sentence classification is not required for v0.1  
- LLM call → optional connector via `citalio[llm]`  
- Search + score + insert → `CitationRepository.search_references()` + optional scorer connector + `CitationInserter`  
- `run_citalio()` async orchestration → becomes `core/workflow.py` functions operating on DB-backed decisions

**Note:** Do not import any `app.services.checker.*` module in standalone Citalio. The classifier/extractor/splitter trio is a Veritas-only dependency.

**Blocker:** Phase 3 (document decisions model) must exist before a meaningful workflow can be assembled. Phase 4 (Step 8/9/10) is when this becomes a shipping feature.

---

### `manual_search.py`

**Current coupling:** Not inspected in this pass (file exists but was not in the priority list).

**Classification:** Inspect before porting

**Action:** Read the file in Phase 2 or Phase 3. If it contains only UI/API routing for manual candidate selection, it may map to a CLI command (`citalio refs search`) or an MCP tool. If it calls Veritas internals, classify as rewrite.

---

### Other Veritas-coupled Citalio files (not in `services/citalio/`)

| File | Classification | Notes |
|------|---------------|-------|
| `backend/app/routes/citalio_routes.py` | Archive | FastAPI routes wired to Veritas app; not portable |
| `backend/cli/citalio_handlers.py` | Inspect | May contain portable workflow logic; check before Phase 4 |
| `frontend/src/components/citalio/` | Archive | React components for Veritas UI; not ported to standalone |
| `frontend/src/lib/api/citalio.ts` | Archive | Veritas API client; standalone CLI/GUI will have its own |
| `scholarly-hollows/` copies | Archive | Duplicate of backend services; same classification applies |
| `docs/PRD-citalio.md` | Reference | Keep as historical PRD; superseded by standalone plan |
| `docs/IMPL-citalio-manual.md` | Reference | Keep; may inform Step 8/9 implementation notes |

---

## Sakura Ref / Veritas Core

No directory named `SakuraRef`, `sakura`, or `SakuraRef` was found under `/home/lily/projects/`. This project does not exist as a separate repository. All relevant Citalio prior art is in Veritas.

---

## Replacement Path Summary

| Veritas dependency | Standalone replacement |
|--------------------|----------------------|
| `VFProfileStore` / Qdrant | `citalio/db/repository.py` `search_references()` (lexical); `search_semantic()` optional via `citalio[semantic]` |
| `app.services.checker.splitter` | stdlib `re` sentence splitter in `citalio/core/workflow.py` (MVP); optional `spacy` later |
| `app.services.checker.extractor` | Deferred — not required for v0.1 decision-driven workflow |
| `app.services.checker.classifier` | Deferred — not required for v0.1 |
| `_default_llm_call` | Optional LLM connector via `citalio[llm]` |
| `SentenceRAGResults` | Not ported; replaced by `citalio/db/models.py` result types |

---

## Phase Gating

| Phase | Prerequisite from this inventory |
|-------|----------------------------------|
| Phase 1 | No blockers — skeleton only |
| Phase 2 | `CitationCandidate` dataclass → `citalio/db/models.py`; lexical search in repository |
| Phase 3 | Document decisions model — no Veritas dependency |
| Phase 4 | Port `CitationInserter` → `markdown_insertion.py`; wire to approved decisions from DB |
| Phase 7 | Port `RelevanceScorer` → `citalio/connectors/hashi.py` or `llm.py` |
| Never | Do not import `app.services.checker.*` in standalone Citalio |
