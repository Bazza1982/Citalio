"""LLM / embedding connectors for semantic search (citalio[semantic] extra).

To configure, set the ``CITALIO_EMBEDDING_MODEL`` environment variable to one
of the built-in connector names, or call ``get_connector()`` with the name
and then call ``connector.configure(**kwargs)`` before indexing.

Built-in connectors
-------------------
bge-m3
    Uses BAAI/bge-m3 via the FlagEmbedding library (local, ~1.2 GB download
    on first use).  Install: ``pip install 'citalio[semantic]'``

openai
    Uses the OpenAI Embeddings API.  Install: ``pip install openai``
    Set ``OPENAI_API_KEY`` or pass ``api_key`` to ``configure()``.

Custom connectors
-----------------
Subclass ``EmbeddingConnector`` and register via ``register_connector()``.
"""

from __future__ import annotations

import importlib
from typing import Any

from citalio.connectors.base import ConnectorError


class EmbeddingConnector:
    """Base class for embedding model connectors.

    Subclass this and override ``embed`` / ``embed_batch``.
    ``name`` must be a unique identifier (used as the ``embedding_id`` in DB).
    ``dimensions`` should match the model output size.
    """

    name: str = ""
    dimensions: int = 0

    def configure(self, **kwargs: Any) -> None:
        """Apply model-specific settings (model name, API key, fp16, etc.)."""

    def embed(self, text: str) -> list[float]:
        """Return a dense embedding vector for a single text string."""
        raise NotImplementedError

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Return embedding vectors for a list of texts.

        Default implementation calls ``embed()`` one at a time; override for
        real batching.
        """
        return [self.embed(t) for t in texts]


# ---------------------------------------------------------------------------
# BGE-M3 connector (FlagEmbedding)
# ---------------------------------------------------------------------------

class BGEM3Connector(EmbeddingConnector):
    """Embedding connector using BAAI/bge-m3 via FlagEmbedding.

    The model (~1.2 GB) is downloaded automatically from HuggingFace on first
    use and cached in ``~/.cache/huggingface/``.

    Install:
        pip install 'citalio[semantic]'

    Usage::

        connector = BGEM3Connector()
        connector.configure(model_name="BAAI/bge-m3", use_fp16=False)
    """

    name = "bge-m3"
    dimensions = 1024

    def __init__(self) -> None:
        self._model: Any = None
        self._model_name = "BAAI/bge-m3"
        self._max_length = 512
        self._use_fp16 = False

    def configure(  # type: ignore[override]
        self,
        model_name: str = "BAAI/bge-m3",
        max_length: int = 512,
        use_fp16: bool = False,
        **_: Any,
    ) -> None:
        self._model_name = model_name
        self._max_length = max_length
        self._use_fp16 = use_fp16
        self._model = None  # force reload

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            FlagModel = importlib.import_module("FlagEmbedding").FlagModel
        except ImportError as exc:
            raise ConnectorError(
                "FlagEmbedding not installed.",
                connector="bge-m3",
                extra="semantic",
            ) from exc
        self._model = FlagModel(
            self._model_name,
            use_fp16=self._use_fp16,
            max_length=self._max_length,
        )
        return self._model

    def embed(self, text: str) -> list[float]:
        vecs = self._load().encode([text], batch_size=1)["dense_vecs"]
        return vecs[0].tolist()

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        vecs = self._load().encode(texts, batch_size=batch_size)["dense_vecs"]
        return [v.tolist() for v in vecs]


# ---------------------------------------------------------------------------
# OpenAI connector
# ---------------------------------------------------------------------------

class OpenAIEmbeddingConnector(EmbeddingConnector):
    """Embedding connector using the OpenAI Embeddings API.

    Requires the ``openai`` package (not included in any citalio extra).

    Install:
        pip install openai

    Usage::

        connector = OpenAIEmbeddingConnector()
        connector.configure(model="text-embedding-3-small", api_key="sk-...")
        # or set OPENAI_API_KEY in environment
    """

    name = "openai"
    dimensions = 1536  # text-embedding-3-small default

    def __init__(self) -> None:
        self._client: Any = None
        self._model = "text-embedding-3-small"
        self._api_key: str | None = None

    def configure(  # type: ignore[override]
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        **_: Any,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._client = None  # force reload

    def _load(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            openai = importlib.import_module("openai")
        except ImportError as exc:
            raise ConnectorError(
                "openai package not installed. Run: pip install openai",
                connector="openai",
            ) from exc
        import os
        self._client = openai.OpenAI(api_key=self._api_key or os.environ.get("OPENAI_API_KEY"))
        return self._client

    def embed(self, text: str) -> list[float]:
        return self._load().embeddings.create(input=[text], model=self._model).data[0].embedding

    def embed_batch(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        client = self._load()
        results: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = client.embeddings.create(input=batch, model=self._model)
            results.extend(d.embedding for d in resp.data)
        return results


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_CONNECTORS: dict[str, type[EmbeddingConnector]] = {
    "bge-m3": BGEM3Connector,
    "openai": OpenAIEmbeddingConnector,
}


def register_connector(name: str, cls: type[EmbeddingConnector]) -> None:
    """Register a custom embedding connector class by name."""
    _CONNECTORS[name] = cls


def get_connector(name: str) -> EmbeddingConnector:
    """Return a fresh connector instance by name.

    Raises ``ValueError`` for unknown names.  Call ``connector.configure()``
    before first use if you need non-default settings.
    """
    cls = _CONNECTORS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown embedding connector: {name!r}. "
            f"Available: {sorted(_CONNECTORS)}"
        )
    return cls()


def list_connectors() -> list[str]:
    """Return names of all registered connectors."""
    return sorted(_CONNECTORS)
