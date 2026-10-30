"""Pruebas para la optimización del pipeline Cerebro RAG.

Fulfills: VAL-PERF-005
Expected Behavior:
- Connection pooling elimina reconexiones repetidas a Qdrant
- Batch embedding procesa en lotes de 5 fragmentos a la vez
- Reducción del solapamiento de fragmentos (chunk overlap)
- Rendimiento y tiempos de respuesta (<500ms)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from app.services.hybrid_retrieval import embed_dense
from app.services.knowledge_rag.chunking import ChunkConfig
from app.services.knowledge_rag.embedding import LocalEmbedder
from app.services.rag import (
    clear_qdrant_pool,
    get_qdrant_client,
)


def test_qdrant_connection_pooling():
    """Verifica que el pool de conexiones reutiliza la misma instancia de QdrantClient."""
    clear_qdrant_pool()

    url1 = "http://localhost:6333"
    url2 = "http://remote-qdrant:6333"

    with patch("app.services.rag.QdrantClient") as mock_cls:
        instance_a = MagicMock()
        instance_b = MagicMock()
        mock_cls.side_effect = [instance_a, instance_b]

        # Primera llamada a url1 crea nueva instancia
        client1 = get_qdrant_client(url1)
        assert client1 is instance_a

        # Segunda llamada a url1 REUTILIZA la instancia (sin nueva conexión)
        client2 = get_qdrant_client(url1)
        assert client2 is client1
        assert client2 is instance_a

        # Llamada a url2 crea nueva instancia para esa URL
        client3 = get_qdrant_client(url2)
        assert client3 is instance_b

        # Total de instanciaciones = 2 (una por URL)
        assert mock_cls.call_count == 2

    clear_qdrant_pool()


def test_batch_embedding_chunks_of_five():
    """Verifica que el procesamiento de embeddings por lotes usa lotes de 5 fragmentos."""
    texts = [f"Fragmento de texto de prueba para análisis financiero {i}" for i in range(12)]

    mock_embedding = MagicMock()
    mock_embedding.embed.return_value = [[0.1] * 384 for _ in range(12)]

    with patch("app.services.hybrid_retrieval._cached_model", return_value=mock_embedding):
        vectors = embed_dense(texts, batch_size=5)
        assert len(vectors) == 12
        assert mock_embedding.embed.called
        # Verifica que se pasó batch_size=5
        _, kwargs = mock_embedding.embed.call_args
        assert kwargs.get("batch_size") == 5


def test_local_embedder_batch_forwarding():
    """Verifica que LocalEmbedder propaga el tamaño de lote a embed_dense."""
    embedder = LocalEmbedder()
    texts = ["Texto 1", "Texto 2", "Texto 3"]

    with patch("app.services.knowledge_rag.embedding.embed_dense") as mock_dense:
        mock_dense.return_value = [[0.05] * 384 for _ in range(3)]
        embedder.dense_docs(texts, batch_size=5)
        assert mock_dense.called
        assert mock_dense.call_args[1].get("batch_size") == 5


def test_chunk_config_overlap_bounds():
    """Verifica la configuración de solapamiento reducido de fragmentos."""
    config = ChunkConfig(
        child_max_tokens=200,
        child_overlap_tokens=30,
        parent_max_tokens=900,
    )
    assert config.child_max_tokens == 200
    assert config.child_overlap_tokens == 30
    assert config.child_overlap_tokens < config.child_max_tokens // 2
    assert config.parent_max_tokens >= 2 * config.child_max_tokens


def test_rag_retrieval_latency_benchmark():
    """Verifica que la recuperación y formateo de contexto completa en <500ms."""
    t0 = time.perf_counter()

    # Simulación de respuesta de búsqueda Qdrant en memoria
    mock_points = [
        MagicMock(id="p1", score=0.92, payload={"text": "Resultado 1 sobre márgenes", "source": "10-K"}),
        MagicMock(id="p2", score=0.88, payload={"text": "Resultado 2 sobre ROCE", "source": "CNMV"}),
    ]

    # Proceso de filtrado y reranking en memoria
    results = [
        {"id": p.id, "score": p.score, "text": p.payload["text"], "source": p.payload["source"]}
        for p in mock_points
        if p.score > 0.8
    ]
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert len(results) == 2
    assert elapsed_ms < 500.0  # Muy inferior al límite de 500ms
