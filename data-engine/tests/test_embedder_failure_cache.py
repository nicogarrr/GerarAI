"""El fallo de carga del modelo fastembed se cachea como el exito.

5-nov-2026 [medido piloto]: sin cachear el fallo, cada lote de embeddings
reintentaba construir TextEmbedding (intento de descarga incluido) y caia al
fallback sentence-transformers: "fallback repetido", worker a 103 % CPU.
Ahora: una construccion fallida, la MISMA excepcion relanzada despues.
"""
from __future__ import annotations

import sys
import types

import pytest

from app.services import hybrid_retrieval as hr


def _fake_failing(monkeypatch, counter):
    module = types.ModuleType("fastembed")

    class FakeDense:
        def __init__(self, model):
            counter["n"] += 1
            raise RuntimeError("modelo sin pesos locales")

        def embed(self, texts, batch_size=None):
            return []

    module.TextEmbedding = FakeDense
    monkeypatch.setitem(sys.modules, "fastembed", module)


def test_fallo_de_carga_se_intenta_una_sola_vez(monkeypatch):
    counter = {"n": 0}
    _fake_failing(monkeypatch, counter)
    hr.clear_model_cache()
    with pytest.raises(RuntimeError, match="sin pesos"):
        hr.embed_dense(["a"])
    with pytest.raises(RuntimeError, match="sin pesos"):
        hr.embed_dense(["b"])
    assert counter["n"] == 1


def test_fallo_cacheado_relanza_la_misma_excepcion(monkeypatch):
    counter = {"n": 0}
    _fake_failing(monkeypatch, counter)
    hr.clear_model_cache()
    first = second = None
    try:
        hr.embed_dense(["a"])
    except RuntimeError as exc:
        first = exc
    try:
        hr.embed_dense(["b"])
    except RuntimeError as exc:
        second = exc
    assert first is not None and first is second


def test_clear_model_cache_permite_reintentar(monkeypatch):
    counter = {"n": 0}
    _fake_failing(monkeypatch, counter)
    hr.clear_model_cache()
    with pytest.raises(RuntimeError):
        hr.embed_dense(["a"])
    hr.clear_model_cache()
    with pytest.raises(RuntimeError):
        hr.embed_dense(["b"])
    assert counter["n"] == 2
