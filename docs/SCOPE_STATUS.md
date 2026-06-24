# Citalio — Scope and Surface Status

Last updated: 2026-06-24 (alpha release preparation)
Accepted by: xishi@HASHI1

---

## Release status

| Item | Status |
|------|--------|
| Public alpha tag | `0.1.0a1` |
| Backward compatibility promise | None beyond alpha experimentation |
| CI | GitHub Actions — Python 3.10 / 3.11 / 3.12 |
| License | MIT (`LICENSE`) |
| Privacy / data safety | `SECURITY.md` |

---

## Alpha-stable surfaces

These are the intended public entry points for the alpha release:

| Surface | Entry point | Status |
|---------|-------------|--------|
| DB connection + migration runner | `citalio/db/connection.py` | ✅ Alpha-stable |
| Initial schema (`001_initial_schema.sql`) | `citalio/db/migrations/` | ✅ Alpha-stable |
| CLI `init` + `db status` | `citalio/cli/main.py` | ✅ Alpha-stable |
| CLI `db backup` + `db restore` | `citalio/db/backup.py` | ✅ Alpha-stable |
| Connector base protocols | `citalio/connectors/base.py` | ✅ Alpha-stable |
| Migration inventory | `docs/migration_inventory.md` | ✅ Alpha-stable |

---

## Prototype surfaces (Phase 2–8)

The following modules are accepted into the repo for continuity but are **not**
alpha-stable product scope. CLI and MCP entry points are labelled `[PROTOTYPE]`.

| Surface | Module | Phase | Guard / Note |
|---------|--------|-------|--------------|
| Citation repository | `citalio/db/repository.py` | 2 | Prototype — schema assumptions documented but not frozen |
| CSL JSON import/export | `citalio/formats/` | 2 | Prototype |
| BibTeX import/export | `citalio/formats/` | 2 | Prototype |
| Zotero metadata/notes import | `citalio/formats/zotero_csl.py` | 2 | Prototype — file-based migration |
| Zotero local sync | `citalio/connectors/zotero.py` | 2 | Prototype — read-only local API adapter |
| Projects / decisions | `citalio/projects/` | 3 | Prototype |
| Review Excel | `citalio/review/` | 4 | Prototype |
| MCP server | `citalio/mcp/server.py` | 5 | Prototype |
| GUI | `citalio/gui/` | 6 | Skeleton only |
| LLM connector + semantic search | `citalio/connectors/llm.py`, `citalio/search/semantic.py` | 8 | Prototype — requires `citalio[semantic]` extra |
| **Word rendering (Step 9)** | `citalio/rendering/word.py` | 9 | **BLOCKED** — `_allow_experimental=True` required; CLI stub raises immediately |

---

## Hardening checklist (complete)

- [x] `repository.py` — transaction atomicity fixed; regression tests added
- [x] Import/export — CSL JSON and BibTeX round-trip tests
- [x] Schema assumptions doc (`docs/local_database_schema.md`)
- [x] CLI command audit — Phase 2–8 labelled `[PROTOTYPE]`
- [x] MCP surface audit — prototype tools labelled in docstrings
- [x] Step 9 design — `docs/word_rendering_guardrail.md`
- [x] DB backup/restore — validated SQLite copy + pre-restore safety backup
- [x] Zotero local sync — staged import with pre-sync backup

---

## Alpha release checklist

- [x] `LICENSE` (MIT)
- [x] `SECURITY.md`
- [x] README downgraded to alpha/prototype tone
- [x] Version bumped to `0.1.0a1`
- [x] GitHub Actions CI workflow
- [x] Public smoke fixture (`tests/fixtures/sample_csl.json`)
- [x] `.gitignore` excludes local DBs, `.citalio/`, `imports/`
- [x] Merge `feature/zotero-metadata-migration` → `main`
- [x] Local git tag `v0.1.0a1`
- [ ] Push `main` + tag to GitHub
- [ ] Create GitHub Release `Citalio 0.1.0 alpha 1`

---

## Step 9 Word Rendering Policy

Step 9 (`render docx`) is **explicitly deferred** until a guardrail-compliant
minimal XML/run-level patch strategy is implemented and tested.

Current state:
- `citalio/rendering/word.py` exists but requires `_allow_experimental=True`
- `citalio render docx` raises immediately with a clear error message
- Design documented in `docs/word_rendering_guardrail.md`

Do not remove the guard or wire Step 9 into default CLI/MCP until ALL criteria
in `docs/word_rendering_guardrail.md` are met and reviewed.