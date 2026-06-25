# Citalio CLI and MCP Usage

Last updated: 2026-06-26
Release target: `0.1.0a1`

This guide explains how humans and AI agents should use Citalio during the alpha
release. The stable boundary is intentionally small. Anything marked
`[PROTOTYPE]` can change before a stable `0.1.0` release.

For the authoritative surface list, see [SCOPE_STATUS.md](SCOPE_STATUS.md).

## Interface Summary

| Audience | Interface | Status | Use it for |
|----------|-----------|--------|------------|
| Human operators | `citalio` CLI | Stable core, prototype workflows | Library setup, backups, imports, searches, review workflows |
| AI agents | `citalio mcp serve` | Prototype | Searching, inspecting, and updating a Citalio library through MCP |
| Local browser users | `citalio gui serve` | Prototype skeleton | Manual browsing and review of references/projects |
| Python callers | `citalio.*` modules | Internal/prototype except documented base protocols | Tests, extensions, and future integrations |

## Library Location

Citalio stores one SQLite database named `citalio.db` inside a library
directory.

Default:

```bash
~/.citalio
```

For release smoke tests and first experiments, always use a dedicated library:

```bash
export CITALIO_HOME="$(mktemp -d)/citalio-library"
citalio init
```

Every CLI and MCP entry point accepts the same library convention:

```bash
citalio <command> --library <path>
CITALIO_HOME=<path> citalio <command>
citalio mcp serve --library <path>
```

Do not point alpha builds at an important Zotero or writing project without a
fresh Citalio backup.

## Human CLI Usage

### Alpha-stable commands

These are the intended public alpha entry points:

```bash
citalio init --library <path>
citalio db status --library <path>
citalio db backup --library <path> [--label <name>]
citalio db restore --library <path> --backup <backup.db> --yes
```

Operational guidance:

- Run `citalio init` before any other command.
- Run `citalio db backup` before imports, syncs, review-sheet application, or
  any prototype write workflow.
- Prefer `--library <path>` in scripts so commands are explicit and reproducible.
- Use `CITALIO_HOME` only when running a focused shell session against one
  library.

### Prototype import and search

```bash
citalio import csl-json --library <path> --file tests/fixtures/sample_csl.json
citalio import bibtex --library <path> --file my_library.bib
citalio refs search --library <path> "neural networks"
citalio refs show --library <path> <reference-uuid>
```

These commands are useful for alpha validation, but their output shape and merge
rules are not yet a stable API.

### Prototype Zotero local sync

```bash
citalio sync zotero-local --library <path> --dry-run
citalio sync zotero-local --library <path>
```

The Zotero local sync is read-only with respect to Zotero. It reads Zotero's
local HTTP API, imports top-level reference metadata and notes into Citalio,
does not read Zotero SQLite directly, does not write to Zotero, and does not copy
PDFs or attachments.

Safety rules:

- First run with `--dry-run`.
- Use a sacrificial Citalio library for first tests.
- Confirm the generated report before running the write path.
- Keep the pre-sync Citalio backup.

### Prototype project and review workflow

The project, candidate, review, render markdown, and validation commands are
available for alpha testing. Treat them as workflow prototypes:

```bash
citalio project create --library <path> --name "Draft chapter" --markdown draft.md
citalio project list --library <path>
citalio review generate --library <path> <project-id> --out review.xlsx
citalio review apply --library <path> <project-id> --file review.xlsx
citalio render markdown --library <path> <project-id>
citalio validate project --library <path> <project-id>
```

Step 9 Word rendering is not available in alpha:

```bash
citalio render docx <project-id>
```

That command intentionally fails fast. Do not document or market Word rendering
as supported until [word_rendering_guardrail.md](word_rendering_guardrail.md) is
satisfied.

## AI Agent MCP Usage

Install the MCP extra:

```bash
pip install 'citalio[mcp]'
```

Run over stdio for local agent clients:

```bash
citalio mcp serve --library <path>
```

Run over SSE only when an MCP client explicitly needs HTTP/SSE:

```bash
citalio mcp serve --library <path> --transport sse
```

Recommended agent configuration:

```json
{
  "command": "citalio",
  "args": ["mcp", "serve", "--library", "/absolute/path/to/citalio-library"]
}
```

Use an absolute `--library` path for agent integrations. This prevents an agent
from accidentally reading or mutating `~/.citalio` when the working directory or
environment changes.

### MCP resources

The server exposes read-oriented resources:

| Resource | Purpose |
|----------|---------|
| `citalio://library/references` | List reference summaries |
| `citalio://library/references/{reference_id}` | Read one reference |
| `citalio://library/references/{reference_id}/notes` | Read notes for one reference |
| `citalio://library/references/{reference_id}/chunks` | Read indexed semantic chunks |
| `citalio://projects` | List document projects |
| `citalio://projects/{project_id}` | Read one project |
| `citalio://projects/{project_id}/decisions` | Read project citation decisions |
| `citalio://projects/{project_id}/validation` | Read validation report |

### MCP tools

The server exposes these tools:

| Tool | Write? | Purpose |
|------|--------|---------|
| `search_references` | No | Keyword search references |
| `get_reference` | No | Read a reference by UUID |
| `find_by_doi` | No | Look up a reference by DOI |
| `create_reference` | Yes | Create/upsert a reference and record provenance |
| `add_note` | Yes | Add a note and record provenance |
| `add_attachment` | Yes | Record a local attachment path |
| `create_project` | Yes | Create a document citation project |
| `load_project` | No | Read project details and stats |
| `import_sidecar` | Yes | Import sidecar decisions into a project |
| `export_sidecar` | Yes | Write sidecar decisions to a JSON file |
| `list_candidates` | No | List project citation decisions |
| `approve_candidate` | Yes | Approve a decision and record provenance |
| `reject_candidate` | Yes | Reject a decision and record provenance |
| `repair_candidate` | Yes | Mark a decision as `needs_repair` |
| `run_step8_markdown_insertion` | Yes | Insert markdown citation markers in-place |
| `run_step10_validation` | No | Validate decisions against markdown |
| `generate_review_excel` | Yes | Write an Excel review sheet |
| `apply_review_excel` | Yes | Apply an edited Excel review sheet |

### Agent safety rules

- Prefer read tools first: `search_references`, `get_reference`,
  `find_by_doi`, `load_project`, `list_candidates`, and validation resources.
- Before write tools, state the intended change and target library path.
- Back up the library with the CLI before bulk writes:
  `citalio db backup --library <path> --label before-agent-run`.
- Do not run `run_step8_markdown_insertion` on an important draft unless the
  user has approved in-place edits.
- Do not treat Step 9 Word rendering as available; MCP intentionally does not
  expose it.
- Do not use MCP to copy PDFs or scrape Zotero storage. Citalio alpha tracks
  metadata, notes, provenance, and local attachment paths only.

## Release Smoke Test

Use this sequence before publishing an alpha tag:

```bash
python -m pip install -e ".[dev,word,gui,mcp]"
python -m pytest -q

tmp="$(mktemp -d)"
lib="$tmp/citalio-library"

citalio init --library "$lib"
citalio db status --library "$lib"
citalio db backup --library "$lib" --label smoke
citalio import csl-json --library "$lib" --file tests/fixtures/sample_csl.json
citalio refs search --library "$lib" "Citalio"
citalio mcp serve --library "$lib" --help
```

The smoke test should not create tracked files and should not require private
Zotero data.
