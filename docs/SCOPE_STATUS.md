# Citalio — Scope and Surface Status

Last updated: 2026-05-10 (hardening pass complete)
Accepted by: xishi@HASHI1

---

## Supported Surfaces (Phase 0/1)

These are stable, reviewed, and accepted as production scope:

| Surface | Entry point | Status |
|---------|-------------|--------|
| DB connection + migration runner | `citalio/db/connection.py` | ✅ Stable |
| Initial schema (`001_initial_schema.sql`) | `citalio/db/migrations/` | ✅ Stable |
| CLI `init` + `db status` | `citalio/cli/main.py` | ✅ Stable |
| Connector base protocols | `citalio/connectors/base.py` | ✅ Stable |
| Migration inventory | `docs/migration_inventory.md` | ✅ Stable |

---

## Experimental / Prototype Surfaces (Phase 2–8)

The following modules were implemented as an **expanded prototype baseline**. They are accepted into the repo for continuity but are **not considered stable product scope**. They must not be presented as production-ready features and remain subject to hardening review before promotion.

| Surface | Module | Phase | Guard / Note |
|---------|--------|-------|--------------|
| Citation repository | `citalio/db/repository.py` | 2 | Prototype — schema assumptions not yet locked |
| CSL JSON import/export | `citalio/formats/` | 2 | Prototype |
| BibTeX import/export | `citalio/formats/` | 2 | Prototype |
| Projects / decisions | `citalio/projects/` | 3 | Prototype |
| Review Excel | `citalio/review/` | 4 | Prototype |
| MCP server | `citalio/mcp/server.py` | 5 | Prototype — not wired to stable CLI |
| GUI | `citalio/gui/` | 6 | Skeleton only |
| LLM connector + semantic search | `citalio/connectors/llm.py`, `citalio/search/semantic.py` | 8 | Prototype — requires `citalio[semantic]` extra |
| **Word rendering (Step 9)** | `citalio/rendering/word.py` | 9 | **GUARDED** — `_allow_experimental=True` required; CLI stub raises immediately; do NOT promote until XML/run-level minimal patch strategy is designed and tested |

---

## Hardening Checklist (next phase — no new features)

- [x] `repository.py` — full behaviour audit: transaction atomicity fixed (single-commit create/upsert), `list_references()` added, upsert edge cases covered by regression tests
- [x] Import/export — round-trip tests for CSL JSON and BibTeX; error-input tests added; DOI whitespace normalization added
- [x] Schema assumptions doc (`docs/local_database_schema.md`) — **created** — locks field types, constraints, merge rules, provenance rules, concurrency model
- [x] CLI command audit — all Phase 2–8 command groups and commands labelled `[PROTOTYPE]`; Step 9 remains blocked; stable commands (`init`, `db status`) unchanged
- [x] MCP surface audit — all Phase 2–8 MCP tools labelled `[PROTOTYPE]` in docstrings; Step 9 not exposed; search/get (read-only, no prototype state) left as-is
- [x] Experimental guardrails — Phase 2–8 CLI/MCP surface is clearly marked `[PROTOTYPE]`; Step 9 Word rendering remains behind `_allow_experimental=True` guard
- [x] Step 9 design — XML/run-level minimal patch strategy documented in `docs/word_rendering_guardrail.md`; guard removal criteria defined

---

## Step 9 Word Rendering Policy

Step 9 (`render docx`) is **explicitly deferred** until a guardrail-compliant minimal XML/run-level patch strategy is implemented and tested.

Current state:
- `citalio/rendering/word.py` exists but requires `_allow_experimental=True` to run
- `citalio render docx` raises immediately with a clear error message
- Tests call with `_allow_experimental=True` to cover the experimental path
- Design for the safe implementation is documented in `docs/word_rendering_guardrail.md`

Do not remove the guard or wire Step 9 into default CLI/MCP until ALL criteria in `docs/word_rendering_guardrail.md` are met and xishi@HASHI1 has reviewed.
