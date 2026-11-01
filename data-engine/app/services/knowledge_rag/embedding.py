"""Embeddings locales del knowledge RAG: denso (ONNX/fastembed) + sparse BM25.

Reutiliza app.services.hybrid_retrieval (misma cache de modelos). La diferencia
con el RAG de portfolio: el BM25 de documentos y de consulta se calculan por
separado (``embed`` vs ``query_embed``), porque la coleccion usa modifier IDF.

Contrato E5 (familia intfloat/*e5*): los documentos se embeben con el prefijo
"passage: " y las consultas con "query: " (ficha oficial del modelo). fastembed
NO los anade (su query_embed/passage_embed delegan en embed), asi que se ponen
aqui. El MiniLM del vector chat legacy no lleva prefijos y no se toca.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.services.hybrid_retrieval import (
    DEFAULT_DENSE_MODEL,
    DEFAULT_SPARSE_MODEL,
    SparseEmbedding,
    _cached_model,
    embed_dense,
)


def needs_e5_prefixes(model: str) -> bool:
    """La familia E5 exige prefijos "query: "/"passage: "; el resto no."""
    return "e5" in model.rsplit("/", 1)[-1].lower()


class Embedder(Protocol):
    dims: int

    def dense_docs(self, texts: list[str]) -> list[list[float]]: ...

    def dense_query(self, text: str) -> list[float]: ...

    def sparse_docs(self, texts: list[str]) -> list[SparseEmbedding]: ...

    def sparse_query(self, text: str) -> SparseEmbedding: ...


class LocalEmbedder:
    """Denso local con prefijos E5 cuando el modelo los exige. ``dims`` es el del
    modelo cargado, no una constante: la coleccion se crea con esta geometria."""

    def __init__(
        self,
        dense_model: str = DEFAULT_DENSE_MODEL,
        sparse_model: str = DEFAULT_SPARSE_MODEL,
        dims: int = 384,
    ):
        self.dense_model = dense_model
        self.sparse_model = sparse_model
        self.dims = dims

    def dense_docs(self, texts: list[str], batch_size: int = 5) -> list[list[float]]:
        if needs_e5_prefixes(self.dense_model):
            texts = [f"passage: {t}" for t in texts]
        return embed_dense(texts, self.dense_model, batch_size=batch_size)

    def dense_query(self, text: str) -> list[float]:
        q = f"query: {text}" if needs_e5_prefixes(self.dense_model) else text
        return embed_dense([q], self.dense_model)[0]

    def _sparse(self) -> Any:
        from fastembed import SparseTextEmbedding

        return _cached_model("sparse", SparseTextEmbedding, self.sparse_model)

    def sparse_docs(self, texts: list[str]) -> list[SparseEmbedding]:
        return [
            SparseEmbedding(indices=list(v.indices), values=list(v.values))
            for v in self._sparse().embed(texts)
        ]

    def sparse_query(self, text: str) -> SparseEmbedding:
        vec = next(iter(self._sparse().query_embed(text)))
        return SparseEmbedding(indices=list(vec.indices), values=list(vec.values))
