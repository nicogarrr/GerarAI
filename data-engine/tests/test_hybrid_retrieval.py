"""Tests hermeticos del modulo hybrid_retrieval (sin modelos, sin Qdrant).

NUNCA descargan modelos: fastembed se mockea via sys.modules y el cliente
Qdrant es un fake en memoria.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from app.services import hybrid_retrieval as hr


def _ranked(ids_scores: list[tuple[str, float]]) -> list[hr.RankedId]:
    return [hr.RankedId(point_id=pid, score=score) for pid, score in ids_scores]


# -- RRF ------------------------------------------------------------------


def test_rrf_union_prefers_present_in_both():
    dense = _ranked([("A", 0.9), ("B", 0.8)])
    sparse = _ranked([("B", 0.7), ("C", 0.6)])
    fused = hr.rrf_fuse(dense, sparse, k=60)
    assert [h.point_id for h in fused] == ["B", "A", "C"]
    top = fused[0]
    assert top.dense_rank == 2 and top.sparse_rank == 1
    assert top.fused_score == pytest.approx(1 / 62 + 1 / 61)
    assert top.dense_score == 0.8 and top.sparse_score == 0.7


def test_rrf_formula_exact_weights():
    dense = _ranked([("X", 0.5)])
    sparse = _ranked([("Y", 0.5)])
    fused = hr.rrf_fuse(dense, sparse, k=10, dense_weight=3.0, sparse_weight=1.0)
    by_id = {h.point_id: h for h in fused}
    assert by_id["X"].fused_score == pytest.approx(3.0 / 11)
    assert by_id["Y"].fused_score == pytest.approx(1.0 / 11)


def test_rrf_weights_flip_winner():
    dense = _ranked([("X", 0.9), ("Y", 0.1)])
    sparse = _ranked([("Y", 0.9), ("X", 0.1)])
    dense_first = hr.rrf_fuse(dense, sparse, k=60, dense_weight=5.0, sparse_weight=1.0)
    assert [h.point_id for h in dense_first] == ["X", "Y"]
    sparse_first = hr.rrf_fuse(dense, sparse, k=60, dense_weight=1.0, sparse_weight=5.0)
    assert [h.point_id for h in sparse_first] == ["Y", "X"]


def test_rrf_k_changes_scores_not_just_order():
    dense = _ranked([("A", 0.9)])
    sparse = _ranked([("A", 0.8)])
    small_k = hr.rrf_fuse(dense, sparse, k=1)
    big_k = hr.rrf_fuse(dense, sparse, k=60)
    assert small_k[0].fused_score > big_k[0].fused_score
    assert small_k[0].fused_score == pytest.approx(2 / 2)


def test_rrf_single_branch_keeps_order_and_marks_missing_none():
    dense = _ranked([("A", 0.9), ("B", 0.5)])
    fused = hr.rrf_fuse(dense, [], k=60)
    assert [h.point_id for h in fused] == ["A", "B"]
    assert fused[0].sparse_score is None and fused[0].sparse_rank is None
    assert hr.rrf_fuse([], []) == []


def test_rrf_tiebreak_deterministic_by_point_id():
    dense = _ranked([("b-doc", 0.1)])
    sparse = _ranked([("a-doc", 0.1)])
    fused = hr.rrf_fuse(dense, sparse, k=60)
    assert [h.point_id for h in fused] == ["a-doc", "b-doc"]
    assert fused[0].fused_score == fused[1].fused_score


# -- helpers ---------------------------------------------------------------


def test_prefetch_limit_oversamples():
    assert hr.prefetch_limit(5) == 30
    assert hr.prefetch_limit(20) == 60
    assert hr.prefetch_limit(1) == 30


def test_hybrid_point_vector_dense_only_returns_list():
    dense = [0.1, 0.2, 0.3]
    assert hr.hybrid_point_vector(dense, None) == dense


def test_hybrid_point_vector_hybrid_returns_named_dict():
    from qdrant_client.models import SparseVector

    dense = [0.1, 0.2, 0.3]
    sparse = hr.SparseEmbedding(indices=[7, 9], values=[0.5, 0.25])
    point = hr.hybrid_point_vector(dense, sparse, "bm25")
    assert point[""] == dense
    assert isinstance(point["bm25"], SparseVector)
    assert list(point["bm25"].indices) == [7, 9]


def test_tenant_filter_always_scopes_tenant():
    from qdrant_client.models import Filter

    only_tenant = hr.tenant_filter(42)
    assert isinstance(only_tenant, Filter)
    assert any(
        c.key == "tenant_id" and c.match.value == 42 for c in only_tenant.must
    )
    with_ticker = hr.tenant_filter(7, ticker="SRCH")
    keys = {c.key for c in with_ticker.must}
    assert {"tenant_id", "ticker"} <= keys


# -- fastembed lazy/mocked --------------------------------------------------


def _fake_fastembed(monkeypatch, dense_vectors=None, sparse_vectors=None):
    module = types.ModuleType("fastembed")

    class FakeDense:
        instances: list = []

        def __init__(self, model):
            self.model = model
            FakeDense.instances.append(self)

        def embed(self, texts, batch_size=None):
            return iter(dense_vectors if dense_vectors is not None else [[0.1] * 4 for _ in texts])

    class FakeSparse:
        def __init__(self, model):
            self.model = model

        def embed(self, texts, batch_size=None):
            return iter(
                sparse_vectors
                if sparse_vectors is not None
                else [types.SimpleNamespace(indices=[1], values=[0.5]) for _ in texts]
            )

    module.TextEmbedding = FakeDense
    module.SparseTextEmbedding = FakeSparse
    monkeypatch.setitem(sys.modules, "fastembed", module)
    return module


def test_embed_dense_passes_model_and_returns_lists(monkeypatch):
    _fake_fastembed(monkeypatch, dense_vectors=[[0.1, 0.2]])
    out = hr.embed_dense(["hola mundo"], "my-model")
    assert out == [[0.1, 0.2]]
    assert hr.fastembed_available() is True


def test_embed_sparse_returns_index_values(monkeypatch):
    _fake_fastembed(monkeypatch)
    out = hr.embed_sparse(["hola mundo"], "Qdrant/bm25")
    assert out == [hr.SparseEmbedding(indices=[1], values=[0.5])]


def test_embed_dense_without_dependency_raises_fastembed_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "fastembed", None)
    assert hr.fastembed_available() is False
    with pytest.raises(hr.FastembedUnavailable):
        hr.embed_dense(["q"])
    with pytest.raises(hr.FastembedUnavailable):
        hr.embed_sparse(["q"])


# -- cliente fake ------------------------------------------------------------


class _FakeCollections:
    def __init__(self, names):
        self.collections = [types.SimpleNamespace(name=n) for n in names]


class _FakeConfig:
    def __init__(self, sparse_names):
        self.params = types.SimpleNamespace(sparse_vectors={n: object() for n in sparse_names})


class _FakeInfo:
    def __init__(self, sparse_names=()):
        self.config = types.SimpleNamespace(params=_FakeConfig(list(sparse_names)).params)


class FakeQdrant:
    def __init__(self, sparse_names=()):
        self.calls: list = []
        self.sparse_names = set(sparse_names)
        self.updated: list = []

    def get_collection(self, name):
        return _FakeInfo(self.sparse_names)

    def get_collections(self):
        return _FakeCollections(["portfolio_research_documents"])

    def update_collection(self, name, **kwargs):
        self.updated.append((name, kwargs))
        self.sparse_names.update(kwargs.get("sparse_vectors_config", {}).keys())
        return True

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(points=[])


def test_collection_has_sparse_true_false_and_error_false():
    assert hr.collection_has_sparse(FakeQdrant({"bm25"}), "c", "bm25") is True
    assert hr.collection_has_sparse(FakeQdrant(), "c", "bm25") is False

    class Boom:
        def get_collection(self, name):
            raise ConnectionError("down")

    assert hr.collection_has_sparse(Boom(), "c", "bm25") is False


def test_ensure_sparse_vector_ok_and_failure_false(caplog):
    client = FakeQdrant()
    assert hr.ensure_sparse_vector(client, "c", "bm25") is True
    assert "bm25" in client.sparse_names

    class Boom:
        def update_collection(self, *args, **kwargs):
            raise RuntimeError("read-only")

    import logging

    with caplog.at_level(logging.WARNING):
        assert hr.ensure_sparse_vector(Boom(), "c", "bm25") is False


def test_sparse_search_uses_named_vector_and_filter():
    from qdrant_client.models import SparseVector

    seen: dict = {}

    class Rec(FakeQdrant):
        def query_points(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(points=["hit"])

    filt = hr.tenant_filter(9, ticker="VCTR")
    out = hr.sparse_search_points(
        Rec(), "c", hr.to_qdrant_sparse(hr.SparseEmbedding([3], [0.4])),
        sparse_name="bm25", query_filter=filt, limit=11,
    )
    assert out == ["hit"]
    assert isinstance(seen["query"], SparseVector)
    assert seen["using"] == "bm25"
    assert seen["query_filter"] is filt
    assert seen["limit"] == 11
