"""Tests for Phase 8 — LLM connector skeleton + semantic search."""

from __future__ import annotations

import json
import math
import sqlite3

import pytest

from citalio.connectors.llm import (
    EmbeddingConnector,
    BGEM3Connector,
    OpenAIEmbeddingConnector,
    get_connector,
    list_connectors,
    register_connector,
)
from citalio.search.semantic import SemanticIndex, SemanticSearchResult, _cosine


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

DIM = 4  # tiny dimension for fast tests


class FixedConnector(EmbeddingConnector):
    """Deterministic connector: returns a unit vector keyed by word count."""

    name = "fixed"
    dimensions = DIM

    def embed(self, text: str) -> list[float]:
        n = len(text.split()) % DIM + 1
        vec = [float(i == n - 1) for i in range(DIM)]
        mag = math.sqrt(sum(v * v for v in vec))
        return [v / mag for v in vec]

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE chunks (
            id            TEXT PRIMARY KEY,
            reference_id  TEXT NOT NULL,
            attachment_id TEXT,
            chunk_index   INTEGER NOT NULL,
            text          TEXT NOT NULL,
            page_start    INTEGER,
            page_end      INTEGER,
            section       TEXT,
            token_count   INTEGER,
            embedding_id  TEXT,
            metadata_json TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );
        """
    )
    return conn


@pytest.fixture
def db():
    return _make_db()


@pytest.fixture
def connector():
    return FixedConnector()


@pytest.fixture
def idx(db, connector):
    return SemanticIndex(db, connector)


# ---------------------------------------------------------------------------
# _cosine
# ---------------------------------------------------------------------------

def test_cosine_identical():
    v = [1.0, 0.0, 0.0]
    assert _cosine(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_zero_vector():
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)


def test_cosine_opposite():
    assert _cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# EmbeddingConnector base
# ---------------------------------------------------------------------------

def test_base_connector_embed_raises():
    c = EmbeddingConnector()
    with pytest.raises(NotImplementedError):
        c.embed("hello")


def test_base_connector_embed_batch_delegates():
    class SimpleConnector(EmbeddingConnector):
        name = "simple"
        dimensions = 2

        def embed(self, text: str) -> list[float]:
            return [1.0, 0.0]

    c = SimpleConnector()
    result = c.embed_batch(["a", "b", "c"])
    assert len(result) == 3
    assert result[0] == [1.0, 0.0]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_list_connectors_includes_builtins():
    names = list_connectors()
    assert "bge-m3" in names
    assert "openai" in names


def test_get_connector_bge_m3():
    c = get_connector("bge-m3")
    assert isinstance(c, BGEM3Connector)


def test_get_connector_openai():
    c = get_connector("openai")
    assert isinstance(c, OpenAIEmbeddingConnector)


def test_get_connector_unknown_raises():
    with pytest.raises(ValueError, match="Unknown embedding connector"):
        get_connector("nonexistent-model")


def test_register_custom_connector():
    class MyConnector(EmbeddingConnector):
        name = "my-model"
        dimensions = 768

        def embed(self, text: str) -> list[float]:
            return [0.0] * 768

    register_connector("my-model", MyConnector)
    c = get_connector("my-model")
    assert isinstance(c, MyConnector)
    assert "my-model" in list_connectors()


# ---------------------------------------------------------------------------
# BGEM3Connector (without loading the actual model)
# ---------------------------------------------------------------------------

def test_bge_m3_configure():
    c = BGEM3Connector()
    c.configure(model_name="BAAI/bge-m3", use_fp16=True, max_length=256)
    assert c._model_name == "BAAI/bge-m3"
    assert c._use_fp16 is True
    assert c._max_length == 256
    assert c._model is None  # reset after configure


def test_bge_m3_embed_raises_without_dep():
    c = BGEM3Connector()
    import sys
    # temporarily shadow FlagEmbedding
    original = sys.modules.get("FlagEmbedding")
    sys.modules["FlagEmbedding"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(Exception):
            c.embed("test")
    finally:
        if original is None:
            sys.modules.pop("FlagEmbedding", None)
        else:
            sys.modules["FlagEmbedding"] = original


# ---------------------------------------------------------------------------
# OpenAIEmbeddingConnector (without calling the API)
# ---------------------------------------------------------------------------

def test_openai_configure():
    c = OpenAIEmbeddingConnector()
    c.configure(model="text-embedding-3-large", api_key="sk-test")
    assert c._model == "text-embedding-3-large"
    assert c._api_key == "sk-test"
    assert c._client is None  # reset


def test_openai_embed_raises_without_dep():
    c = OpenAIEmbeddingConnector()
    import sys
    original = sys.modules.get("openai")
    sys.modules["openai"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(Exception):
            c.embed("test")
    finally:
        if original is None:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = original


# ---------------------------------------------------------------------------
# SemanticIndex — indexing
# ---------------------------------------------------------------------------

def test_add_chunk_stores_row(idx, db):
    chunk_id = idx.add_chunk("ref-001", "machine learning survey")
    row = db.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    assert row is not None
    assert row["reference_id"] == "ref-001"
    assert row["embedding_id"] == "fixed"
    meta = json.loads(row["metadata_json"])
    assert "_embedding" in meta
    assert len(meta["_embedding"]) == DIM


def test_add_chunk_token_count(idx, db):
    chunk_id = idx.add_chunk("ref-001", "one two three four")
    row = db.execute("SELECT token_count FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    assert row["token_count"] == 4


def test_add_chunk_with_metadata(idx, db):
    chunk_id = idx.add_chunk(
        "ref-001", "hello world",
        attachment_id="att-xyz",
        chunk_index=3,
        page_start=10,
        page_end=12,
        section="Introduction",
    )
    row = db.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    assert row["attachment_id"] == "att-xyz"
    assert row["chunk_index"] == 3
    assert row["page_start"] == 10
    assert row["section"] == "Introduction"


def test_index_reference_splits_into_chunks(idx, db):
    long_text = " ".join(f"word{i}" for i in range(1200))
    ids = idx.index_reference("ref-002", long_text, chunk_size=500, overlap=50)
    assert len(ids) >= 2
    count = db.execute("SELECT COUNT(*) FROM chunks WHERE reference_id = 'ref-002'").fetchone()[0]
    assert count == len(ids)


def test_index_reference_empty_text(idx):
    ids = idx.index_reference("ref-003", "")
    assert ids == []


def test_index_reference_short_text(idx, db):
    ids = idx.index_reference("ref-004", "short text here", chunk_size=500)
    assert len(ids) == 1


def test_delete_chunks_for_reference(idx, db):
    idx.index_reference("ref-del", "some abstract text", chunk_size=500)
    deleted = idx.delete_chunks_for_reference("ref-del")
    assert deleted >= 1
    count = db.execute("SELECT COUNT(*) FROM chunks WHERE reference_id = 'ref-del'").fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# SemanticIndex — search
# ---------------------------------------------------------------------------

def test_search_returns_results(idx):
    idx.add_chunk("ref-A", "machine learning neural networks")
    idx.add_chunk("ref-B", "quantum computing algorithms")
    results = idx.search("machine learning", limit=5)
    assert len(results) >= 1
    assert all(isinstance(r, SemanticSearchResult) for r in results)


def test_search_ranking(idx):
    idx.add_chunk("ref-A", "hello world")          # 2-word text
    idx.add_chunk("ref-B", "hello world foo bar")  # 4-word text
    # query "hello world" → same bucket as ref-A → ref-A should score higher
    results = idx.search("hello world", limit=10)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True), "Results must be sorted by descending score"


def test_search_empty_index(idx):
    results = idx.search("anything", limit=5)
    assert results == []


def test_search_limit(idx):
    for i in range(10):
        idx.add_chunk(f"ref-{i}", f"word{i} word{i+1} word{i+2}")
    results = idx.search("word5 word6", limit=3)
    assert len(results) <= 3


def test_search_result_fields(idx):
    idx.add_chunk("ref-X", "test abstract text", section="Abstract", page_start=1, page_end=1)
    results = idx.search("test abstract", limit=1)
    assert len(results) == 1
    r = results[0]
    assert r.reference_id == "ref-X"
    assert r.section == "Abstract"
    assert r.page_start == 1
    assert 0.0 <= r.score <= 1.0


def test_search_excludes_other_connectors(db):
    c1 = FixedConnector()
    c1.name = "connector-alpha"
    c2 = FixedConnector()
    c2.name = "connector-beta"

    idx1 = SemanticIndex(db, c1)
    idx2 = SemanticIndex(db, c2)

    idx1.add_chunk("ref-1", "alpha text here")
    results = idx2.search("alpha text", limit=5)
    assert results == [], "Connector beta should not see connector alpha's chunks"


# ---------------------------------------------------------------------------
# SemanticIndex — stats
# ---------------------------------------------------------------------------

def test_chunk_count(idx):
    assert idx.chunk_count() == 0
    idx.add_chunk("ref-1", "one two three")
    idx.add_chunk("ref-1", "four five six")
    assert idx.chunk_count() == 2


def test_indexed_reference_ids(idx):
    idx.add_chunk("ref-A", "text A")
    idx.add_chunk("ref-B", "text B")
    idx.add_chunk("ref-A", "text A again")
    ids = idx.indexed_reference_ids()
    assert set(ids) == {"ref-A", "ref-B"}
