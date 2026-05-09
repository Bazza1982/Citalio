# Citalio

Citalio is a standalone citation and reference management library for researchers
and writers.  It stores references in a local SQLite database, supports importing
from BibTeX and CSL-JSON, provides semantic (vector) search, and integrates with
AI agents via an MCP server.

## Installation

```bash
pip install citalio          # core library + CLI
pip install 'citalio[mcp]'   # + MCP server support
pip install 'citalio[word]'  # + Word document rendering (experimental)
pip install 'citalio[semantic]'  # + embedding / semantic search
pip install 'citalio[gui]'   # + local web GUI
```

Requires Python 3.10+.

## Quick start

```bash
# Initialise a library in ~/.citalio (or set CITALIO_HOME to change location)
citalio init

# Import references
citalio import csl-json --file my_library.json
citalio import bibtex   --file my_library.bib

# Search
citalio refs search "neural networks"
citalio refs show <reference-uuid>
```

## Embedding / semantic search

Citalio can index reference abstracts as embedding vectors for semantic search.

```bash
citalio embed index        # index all references using the default model
citalio embed search "attention mechanism for long documents"
```

The embedding model is configured via the `CITALIO_EMBEDDING_MODEL` environment
variable (or the `--connector` flag).  The default is **BGE-M3**, which is
downloaded automatically on first use via the `sentence-transformers` library.

```bash
# Use OpenAI embeddings instead
CITALIO_EMBEDDING_MODEL=openai citalio embed index
```

## MCP server

Start the MCP server for use with Claude Code or other MCP-compatible agents:

```bash
citalio mcp serve            # stdio transport (default, for Claude Code)
citalio mcp serve --transport sse  # HTTP/SSE transport
```

## Library location

By default Citalio stores its database at `~/.citalio/citalio.db`.
Set the `CITALIO_HOME` environment variable or pass `--library <path>` to any
command to use a different location.
