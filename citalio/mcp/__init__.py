# mcp: MCP server exposing citation DB and document workflow (citalio[mcp] extra)

from __future__ import annotations


def get_server(library=None):
    """Lazy import so citalio[mcp] is only required when actually used."""
    from citalio.mcp.server import create_server

    return create_server(library)
