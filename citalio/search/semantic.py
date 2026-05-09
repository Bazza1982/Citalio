"""Semantic (embedding-based) search over citalio chunks.

Embeddings are stored as JSON arrays inside ``chunks.metadata_json`` under
the key ``_embedding``, and ``chunks.embedding_id`` is set to the connector
name (e.g. ``"bge-m3"``).  This is portable and requires no extra
infrastructure — suitable for PhD-scale libraries (thousands of references).

For very large libraries (100k+ chunks) consider replacing the in-memory
cosine scan with a dedicated vector store such as FAISS or ChromaDB.
"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from citalio.connectors.llm import EmbeddingConnector

_EMBEDDING_KEY = "_embedding"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


@dataclass
class SemanticSearchResult:
    chunk_id: str
    reference_id: str
    text: str
    score: float
    section: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class SemanticIndex:
    """Manages embedding storage and cosine similarity search for citalio chunks.

    Parameters
    ----------
    conn:
        An open ``sqlite3.Connection`` to the citalio database (must already
        have the ``chunks`` table from migration 001).
    connector:
        An ``EmbeddingConnector`` instance (already configured).

    Example::

        from citalio.connectors.llm import get_connector
        from citalio.search.semantic import SemanticIndex

        connector = get_connector("bge-m3")      # or "openai"
        # connector.configure(use_fp16=True)     # optional tuning

        idx = SemanticIndex(conn, connector)
        idx.index_reference(ref_id, abstract_text)
        results = idx.search("machine learning survey", limit=5)
    """

    def __init__(self, conn: sqlite3.Connection, connector: "EmbeddingConnector") -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._connector = connector

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def add_chunk(
        self,
        reference_id: str,
        text: str,
        *,
        attachment_id: str | None = None,
        chunk_index: int = 0,
        page_start: int | None = None,
        page_end: int | None = None,
        section: str | None = None,
        token_count: int | None = None,
    ) -> str:
        """Embed a single text string and insert it as a chunk row.

        Returns the new ``chunk_id``.
        """
        vector = self._connector.embed(text)
        chunk_id = str(uuid.uuid4())
        now = _now_iso()
        self._conn.execute(
            """
            INSERT INTO chunks
              (id, reference_id, attachment_id, chunk_index, text,
               page_start, page_end, section, token_count,
               embedding_id, metadata_json, created_at, updated_at)
            VALUES
              (:id, :ref, :att, :idx, :text,
               :ps, :pe, :sec, :tc,
               :eid, :meta, :ca, :ua)
            """,
            {
                "id": chunk_id,
                "ref": reference_id,
                "att": attachment_id,
                "idx": chunk_index,
                "text": text,
                "ps": page_start,
                "pe": page_end,
                "sec": section,
                "tc": token_count if token_count is not None else len(text.split()),
                "eid": self._connector.name,
                "meta": json.dumps({_EMBEDDING_KEY: vector}),
                "ca": now,
                "ua": now,
            },
        )
        self._conn.commit()
        return chunk_id

    def index_reference(
        self,
        reference_id: str,
        text: str,
        *,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> list[str]:
        """Split ``text`` into overlapping token windows, embed all, and store.

        Parameters
        ----------
        chunk_size:
            Approximate number of whitespace-separated tokens per chunk.
        overlap:
            Number of tokens to repeat at the start of each successive chunk
            for context continuity.

        Returns the list of inserted ``chunk_id`` values.
        """
        tokens = text.split()
        if not tokens:
            return []

        step = max(1, chunk_size - overlap)
        windows: list[str] = []
        for start in range(0, len(tokens), step):
            window = tokens[start : start + chunk_size]
            windows.append(" ".join(window))
            if start + chunk_size >= len(tokens):
                break

        vectors = self._connector.embed_batch(windows)
        now = _now_iso()
        ids: list[str] = []
        for idx, (chunk_text, vector) in enumerate(zip(windows, vectors)):
            chunk_id = str(uuid.uuid4())
            self._conn.execute(
                """
                INSERT INTO chunks
                  (id, reference_id, chunk_index, text, token_count,
                   embedding_id, metadata_json, created_at, updated_at)
                VALUES (:id, :ref, :idx, :text, :tc, :eid, :meta, :ca, :ua)
                """,
                {
                    "id": chunk_id,
                    "ref": reference_id,
                    "idx": idx,
                    "text": chunk_text,
                    "tc": len(chunk_text.split()),
                    "eid": self._connector.name,
                    "meta": json.dumps({_EMBEDDING_KEY: vector}),
                    "ca": now,
                    "ua": now,
                },
            )
            ids.append(chunk_id)
        self._conn.commit()
        return ids

    def delete_chunks_for_reference(self, reference_id: str) -> int:
        """Remove all indexed chunks for a reference. Returns number deleted."""
        cur = self._conn.execute(
            "DELETE FROM chunks WHERE reference_id = ? AND embedding_id = ?",
            (reference_id, self._connector.name),
        )
        self._conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> list[SemanticSearchResult]:
        """Return top-``limit`` chunks ranked by cosine similarity to ``query``.

        All chunks whose ``embedding_id`` matches the current connector are
        loaded and scored in-memory.  For large corpora, replace this with a
        dedicated ANN index.
        """
        query_vec = self._connector.embed(query)

        rows = self._conn.execute(
            """
            SELECT id, reference_id, text, section, page_start, page_end, metadata_json
            FROM chunks
            WHERE embedding_id = ?
            """,
            (self._connector.name,),
        ).fetchall()

        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            meta = json.loads(row["metadata_json"] or "{}")
            vec = meta.get(_EMBEDDING_KEY)
            if vec is None:
                continue
            scored.append((_cosine(query_vec, vec), row))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[SemanticSearchResult] = []
        for score, row in scored[:limit]:
            meta = json.loads(row["metadata_json"] or "{}")
            extra = {k: v for k, v in meta.items() if k != _EMBEDDING_KEY}
            results.append(
                SemanticSearchResult(
                    chunk_id=row["id"],
                    reference_id=row["reference_id"],
                    text=row["text"],
                    score=score,
                    section=row["section"],
                    page_start=row["page_start"],
                    page_end=row["page_end"],
                    extra=extra,
                )
            )
        return results

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def chunk_count(self) -> int:
        """Return number of chunks indexed with the current connector."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding_id = ?",
            (self._connector.name,),
        ).fetchone()
        return int(row[0]) if row else 0

    def indexed_reference_ids(self) -> list[str]:
        """Return reference IDs that have at least one chunk indexed."""
        rows = self._conn.execute(
            "SELECT DISTINCT reference_id FROM chunks WHERE embedding_id = ?",
            (self._connector.name,),
        ).fetchall()
        return [r[0] for r in rows]
