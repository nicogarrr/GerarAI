"""Circuit breaker fastembed -> sentence-transformers en RAGIndex.

5-nov-2026 [medido piloto]: "fallback repetido fastembed sin modelo local ->
sentence-transformers". Sin freno, CADA lote reintentaba fastembed y logueaba
de nuevo; con freno, se intenta una vez por proceso y el resto va directo al
fallback. Determinista: contadores, sin reloj.
"""
from __future__ import annotations

import app.services.hybrid_retrieval as hr
from app.services.rag import RAGIndex


class _Vectors(list):
    def tolist(self):
        return list(self)


class _FakeST:
    def __init__(self):
        self.calls = 0

    def encode(self, texts, normalize_embeddings=True):
        self.calls += 1
        return _Vectors([[0.1, 0.2] for _ in texts])


def _rag(monkeypatch):
    rag = RAGIndex.__new__(RAGIndex)
    monkeypatch.setattr(RAGIndex, "_fastembed_error", None, raising=False)
    return rag


def test_breaker_intenta_fastembed_una_sola_vez(monkeypatch):
    rag = _rag(monkeypatch)
    st = _FakeST()
    calls = {"n": 0}

    def failing_embed(texts, model=hr.DEFAULT_DENSE_MODEL, batch_size=5):
        calls["n"] += 1
        raise hr.FastembedUnavailable("sin modelo local")

    monkeypatch.setattr(hr, "embed_dense", failing_embed)
    monkeypatch.setattr(RAGIndex, "warm_fallback", classmethod(lambda cls: st))
    monkeypatch.setattr(
        RAGIndex, "_setting", lambda self, k, d=None: d, raising=False
    )

    out1 = rag._dense_vectors(["a", "b"])
    out2 = rag._dense_vectors(["c"])
    out3 = rag._dense_vectors(["d"])

    assert calls["n"] == 1, "fastembed se reintento por lote"
    assert st.calls == 3, "el fallback ST sirvio todos los lotes"
    assert RAGIndex._fastembed_error is not None
    assert len(out1) == 2 and len(out2) == 1 and len(out3) == 1


def test_backend_sentence_transformers_no_toca_fastembed(monkeypatch):
    rag = _rag(monkeypatch)
    st = _FakeST()

    def forbidden(*args, **kwargs):
        raise AssertionError("no debia llamarse")

    monkeypatch.setattr(hr, "embed_dense", forbidden)
    monkeypatch.setattr(RAGIndex, "warm_fallback", classmethod(lambda cls: st))
    monkeypatch.setattr(
        RAGIndex,
        "_setting",
        lambda self, k, d=None: "sentence-transformers" if k == "rag_embedding_backend" else d,
        raising=False,
    )

    rag._dense_vectors(["x"])
    assert st.calls == 1
    assert RAGIndex._fastembed_error is None
