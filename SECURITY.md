# Security and Data Safety

Citalio is a **local-first** citation library. This document describes what the
software reads, writes, and excludes by default.

## Local data

- Citalio stores its database under `~/.citalio/` by default, or any path you
  pass with `--library` / `CITALIO_HOME`.
- Database files (`*.db`, `*.sqlite`) and backup directories are excluded from
  git via `.gitignore`.
- Do not commit real library databases, Zotero exports, PDFs, or review
  spreadsheets into the repository.

## Zotero integration

`citalio sync zotero-local` is **read-only** with respect to Zotero:

- Uses Zotero's local HTTP API only when Zotero is running.
- Does **not** read Zotero's SQLite database directly.
- Does **not** write to Zotero.
- Does **not** copy PDFs or other attachments.
- Imports metadata and notes into Citalio only.

Always use a dedicated test library for first sync experiments, not your
production Zotero library.

## Backups

- `citalio db backup` creates a validated SQLite copy before larger changes.
- `citalio db restore` creates an automatic pre-restore safety backup.
- Zotero local sync also creates a pre-sync backup before publishing staged
  imports.

## Alpha scope

Version `0.1.0a1` is an **alpha** release. APIs, schema details, and prototype
CLI surfaces may change without a major-version guarantee.

## Reporting issues

If you discover a security or data-loss concern, open a GitHub issue with
reproduction steps and redacted sample data only. Do not attach private library
databases or full Zotero exports unless you have explicitly sanitized them.