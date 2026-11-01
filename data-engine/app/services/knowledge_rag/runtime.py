"""Cableado de dependencias desde Settings (Qdrant, embedder, contador, reranker)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings
from app.services.knowledge_rag.chunking import ChunkConfig
from app.services.knowledge_rag.embedding import LocalEmbedder
from app.services.knowledge_rag.extract import extract_file
from app.services.knowledge_rag.ingest import Extractor
from app.services.knowledge_rag.rerank import FastembedReranker, RerankPostprocessor
from app.services.knowledge_rag.store import KnowledgeStore
from app.services.knowledge_rag.tokens import TokenCounter, wordpiece_counter


class KnowledgeRagDisabled(RuntimeError):
    pass


def require_enabled(settings: Settings | None = None) -> Settings:
    s = settings or get_settings()
    if not s.knowledge_rag_enabled:
        raise KnowledgeRagDisabled("knowledge RAG is disabled (KNOWLEDGE_RAG_ENABLED=false)")
    return s


def chunk_config(s: Settings) -> ChunkConfig:
    return ChunkConfig(
        child_max_tokens=s.knowledge_rag_child_max_tokens,
        child_overlap_tokens=s.knowledge_rag_child_overlap_tokens,
        parent_max_tokens=s.knowledge_rag_parent_max_tokens,
    )


@lru_cache(maxsize=4)
def _qdrant_client(url: str):
    """Cached Qdrant client to enable connection pooling."""
    from qdrant_client import QdrantClient

    return QdrantClient(url=url)


def make_store(s: Settings) -> KnowledgeStore:
    return KnowledgeStore(
        _qdrant_client(s.qdrant_url), s.knowledge_rag_collection, dims=s.knowledge_rag_dense_dims
    )


def make_embedder(s: Settings) -> LocalEmbedder:
    return LocalEmbedder(s.knowledge_rag_dense_model, s.rag_sparse_model, dims=s.knowledge_rag_dense_dims)


@lru_cache(maxsize=2)
def make_counter(model: str) -> TokenCounter:
    return wordpiece_counter(model)


def make_extractor(s: Settings) -> Extractor:
    def run(path: Path):
        return extract_file(
            path, ocr=s.knowledge_rag_docling_ocr, table_mode=s.knowledge_rag_docling_table_mode
        )

    return run


def make_postprocessors(s: Settings, top_n: int) -> list[RerankPostprocessor]:
    if not s.knowledge_rag_reranker_model:
        return []
    return [RerankPostprocessor(reranker=_reranker(s.knowledge_rag_reranker_model), top_n=top_n)]


@lru_cache(maxsize=2)
def _reranker(model: str) -> FastembedReranker:
    return FastembedReranker(model)


# Limite por entrega del actor de ingesta (ms). Unica fuente: el actor lo usa
# como time_limit y la API deriva de el cuando una fuente en ``processing`` se
# considera abandonada (2 x este limite).
INGEST_TIME_LIMIT_MS = 3_600_000
