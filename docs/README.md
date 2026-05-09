# Citalio Documentation

This folder contains planning and architecture documents for Citalio.

Current documents:

- [Standalone Citation Database Plan](standalone_citation_database_plan.md): comprehensive plan for making Citalio independent from Zotero while preserving Zotero compatibility through optional adapters. Updated after architecture review to include Phase 0 migration inventory, migration/versioning rules, revised v0.1/v0.2/v0.3 scope, Word rendering guardrails, SQLite concurrency rules, and connector/MCP boundary fixes.

- [Scope and Surface Status](SCOPE_STATUS.md): which surfaces are stable (Phase 0/1) vs experimental prototype (Phase 2–8), hardening checklist, and Step 9 Word rendering policy. (**Hardening pass complete 2026-05-10.**)

- [Local Database Schema](local_database_schema.md): locked field types, constraints, merge/deduplication rules, provenance rules, concurrency model, and migration policy for all 18 tables.

- [Word Rendering Guardrail](word_rendering_guardrail.md): why Step 9 is guarded, the approved XML/run-level minimal-patch algorithm, required test fixtures, and guard-removal criteria.

- [Migration Inventory](migration_inventory.md): inventory of prior Veritas/Qdrant modules and their migration classification.

- [Zotero Metadata Migration Plan](zotero_metadata_migration_plan.md): safety-first plan for importing Zotero-exported reference metadata into the Citalio native database without copying PDFs or modifying Zotero.

Planned follow-up documents:

- `mcp_server_spec.md`
- `gui_product_spec.md`
- `zotero_compatibility_spec.md`
