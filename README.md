# Citalio (alpha)

> **Alpha release (`0.1.0a1`)** — local citation library for researchers and
> writers. Stable surfaces are intentionally small; most CLI commands are marked
> `[PROTOTYPE]` and may change before a stable `0.1.0` release.

Citalio stores references in a local SQLite database, supports importing from
BibTeX and CSL-JSON, and provides optional semantic search and agent integration
via MCP.

See [docs/SCOPE_STATUS.md](docs/SCOPE_STATUS.md) for the authoritative
stable vs prototype surface list.

## Installation

```bash
pip install citalio                    # core library + CLI
pip install 'citalio[dev]'             # development / test extras
pip install 'citalio[mcp]'             # MCP server support (prototype)
pip install 'citalio[word]'            # Word rendering deps (Step 9 blocked)
pip install 'citalio[semantic]'        # embedding / semantic search (prototype)
pip install 'citalio[gui]'             # local web GUI (prototype skeleton)
```

Requires Python 3.10+.

## Alpha-stable surfaces

These commands are the intended alpha entry points:

```bash
citalio init
citalio db status
citalio db backup --library <path> [--label <name>]
citalio db restore --library <path> --backup <file> --yes
```

## Quick start (prototype import/search)

```bash
# Initialise a library (default: ~/.citalio)
citalio init

# Import references — [PROTOTYPE]
citalio import csl-json --file tests/fixtures/sample_csl.json
citalio import bibtex   --file my_library.bib

# Search — [PROTOTYPE]
citalio refs search "neural networks"
citalio refs show <reference-uuid>
```

Set `CITALIO_HOME` or pass `--library <path>` to use a non-default location.

## Zotero local sync — [PROTOTYPE]

When Zotero is open with its local API enabled, Citalio can sync top-level
Zotero reference metadata and Zotero notes **without** reading Zotero SQLite,
writing to Zotero, or copying PDFs/attachments.

```bash
citalio sync zotero-local --library .citalio/zotero-native --dry-run
citalio sync zotero-local --library .citalio/zotero-native
```

The sync fetches a full Zotero snapshot first, validates that parented notes map
to fetched Zotero item keys, stages the import in a temporary database, then
publishes it to Citalio with a pre-sync database backup.

Use a dedicated test library for first experiments.

## Database backups

```bash
citalio db backup --library .citalio/zotero-native --label before-big-change
citalio db backup --library .citalio/zotero-native --output ~/Desktop/citalio-save.db
citalio db restore --library .citalio/zotero-native --backup <backup.db> --yes
```

## Embedding / semantic search — [PROTOTYPE]

Requires `pip install 'citalio[semantic]'`. The default BGE-M3 model downloads
from HuggingFace on first use (~1.2 GB).

```bash
citalio embed index
citalio embed search "attention mechanism for long documents"
```

## MCP server — [PROTOTYPE]

```bash
citalio mcp serve
citalio mcp serve --transport sse
```

## Not available in alpha

- **Step 9 Word rendering** (`citalio render docx`) — blocked by design. See
  [docs/word_rendering_guardrail.md](docs/word_rendering_guardrail.md).
- **Production Zotero migration promises** — metadata/notes sync is prototype;
  validate on sacrificial libraries first.

## Privacy and data safety

See [SECURITY.md](SECURITY.md).

## Development

```bash
python -m pip install -e ".[dev,word,gui,mcp]"
python -m pytest -q
```

Semantic-search tests use lightweight in-memory connectors and do not require
`citalio[semantic]` unless you run embedding integration work locally.