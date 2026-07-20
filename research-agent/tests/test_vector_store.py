import pytest

from src.memory.vector_store import VectorStore
from src.models import Chunk


def _chunk(cid, source_id, text, idx, page=1):
    return Chunk(id=cid, source_id=source_id, text=text, page=page, chunk_index=idx)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "chroma")


def test_query_returns_most_relevant_first(db_path):
    vs = VectorStore(db_path)
    vs.add_chunks([
        _chunk("p1:0", "p1", "transformer models for time series forecasting", 0),
        _chunk("p1:1", "p1", "a study of medieval agriculture and crop rotation", 1),
        _chunk("p1:2", "p1", "convolutional networks for image classification", 2),
    ])
    top = vs.query("time series forecasting with transformers", k=1)
    assert len(top) == 1
    assert top[0].id == "p1:0"


def test_source_id_filter_isolates(db_path):
    vs = VectorStore(db_path)
    vs.add_chunks([
        _chunk("p1:0", "p1", "neural attention mechanisms", 0),
        _chunk("p2:0", "p2", "neural attention mechanisms", 0),
    ])
    results = vs.query("attention", k=10, source_id="p2")
    assert results and all(c.source_id == "p2" for c in results)


def test_persistence_across_instances(db_path):
    VectorStore(db_path).add_chunks([_chunk("p1:0", "p1", "persisted text", 0)])
    reopened = VectorStore(db_path)
    assert reopened.query("persisted", k=1)[0].id == "p1:0"


def test_upsert_does_not_duplicate(db_path):
    vs = VectorStore(db_path)
    vs.add_chunks([_chunk("p1:0", "p1", "original text about cats", 0)])
    vs.add_chunks([_chunk("p1:0", "p1", "replaced text about dogs", 0)])
    rows = vs.query("animals", k=10, source_id="p1")
    assert len(rows) == 1
    assert rows[0].text == "replaced text about dogs"


def test_mmr_strategy_returns_k_diverse_chunks(db_path):
    vs = VectorStore(db_path)
    vs.add_chunks([
        _chunk("p1:0", "p1", "transformers forecast time series data", 0),
        _chunk("p1:1", "p1", "transformers forecast time series data.", 1),
        _chunk("p1:2", "p1", "transformers forecast time series values", 2),
        _chunk("p1:3", "p1", "dataset preprocessing removes seasonal outliers", 3),
    ])
    ids = {c.id for c in vs.query("transformer forecasting", k=2, strategy="mmr", source_id="p1")}
    assert len(ids) == 2
    assert "p1:3" in ids


def test_empty_store_returns_empty(db_path):
    assert VectorStore(db_path).query("anything") == []
