# Citalio — Scope and Surface Status

Last updated: 2026-05-10
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

- [ ] `repository.py` — full behaviour audit (upsert edge cases, creator merge, transaction safety)
- [ ] Import/export — round-trip tests for CSL JSON and BibTeX
- [ ] Schema assumptions doc (`docs/local_database_schema.md`) — lock field types and constraints
- [ ] CLI command audit — confirm only Phase 0/1 commands are exposed by default
- [ ] MCP surface audit — confirm MCP does not expose prototype-only operations
- [ ] Experimental guardrails — verify all Phase 2–8 modules raise clearly when called in unsupported mode
- [ ] Step 9 design — XML/run-level minimal patch strategy before removing guard

---

## Step 9 Word Rendering Policy

Step 9 (`render docx`) is **explicitly deferred** until a guardrail-compliant minimal XML/run-level patch strategy is designed and tested.

Current state:
- `citalio/rendering/word.py` exists but requires `_allow_experimental=True` to run
- `citalio cli render docx` raises `NotImplementedError` immediately
- Tests call with `_allow_experimental=True` to cover the experimental path

Do not remove the guard or wire Step 9 into default CLI/MCP until the strategy is reviewed.
