"""GUI startup helper — run with uvicorn or via `citalio gui serve`."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    library: Optional[Path] = None,
    reload: bool = False,
) -> None:
    """Start the Citalio GUI server with uvicorn."""
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "uvicorn is required for the Citalio GUI. "
            "Install it with: pip install 'citalio[gui]'"
        ) from exc

    from citalio.gui.api import create_app

    application = create_app(library=library)
    print(f"Citalio GUI  →  http://{host}:{port}")
    uvicorn.run(application, host=host, port=port, reload=reload)
