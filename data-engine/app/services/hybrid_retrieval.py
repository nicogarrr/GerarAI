"""Retrieval hibrido denso+sparse sobre Qdrant con fusion RRF (lado cliente).

Diseno para produccion (VM CPU-only, RAM limitada):
- Denso: fastembed (ONNX CPU) con el MISMO modelo de produccion
  (``sentence-transformers/all-MiniLM-L6-v2``, 384 dims). Vectores
  equivalentes al backend torch (coseno ~1.0 medido), sin reindexado.
- Sparse sibling: BM25 estadistico via fastembed (``Qdrant/bm25``, ~10 MB,
  multilingue por construccion). Se eligio frente a SPLADE++ porque los
  modelos SPLADE disponibles en fastembed son solo-ingles
  (``prithivida/Splade_PP_en_v1``, ~0.5 GB) y la biblioteca tiene espanol;
  BM25 ataca exactamente la debilidad medida en FinMTEB (los BoW/BM25
  baten a los densos en similaridad financiera) con coste casi nulo:
  ~0.06 ms/doc y ~70 MB extra frente a ~9.7 ms/doc del denso.
- Fusion RRF en Python (no ``query_points``+prefetch de servidor) para no
  depender de la version de Qdrant (prod ya va en 1.19.2; los pesos de
  servidor exigen >= 1.17, pero la fusion en cliente da el mismo resultado
  sin acoplar al despliegue). Formula (rank 1-based):
  ``score = sum(w / (k + rank))`` por lista, con k y pesos configurables.

Todo import de fastembed es perezoso: sin la dependencia instalada las
funciones de embedding lanzan ``FastembedUnavailable`` y el llamador
(``app/services/rag.py``) degrada a denso-only con warning, nunca 500.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_DENSE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_SPARSE_MODEL = "Qdrant/bm25"
DEFAULT_SPARSE_VECTOR_NAME = "bm25"
DEFAULT_RRF_K = 60

# La coleccion historica usa vector denso anonimo (single); en forma dict
# el servidor lo direcciona con clave vacia. Verificado contra
# qdrant-client local; el path hibrido es opt-in con fallback a denso-only.
DEFAULT_DENSE_VECTOR_NAME = ""

# Prefetch por rama para la fusion: sobremuestrea respecto al limit pedido.
PREFETCH_MULTIPLIER = 3
PREFETCH_MINIMUM = 30


# Cache de modelos por proceso. La clave incluye la clase del modelo para que
# un cambio de implementacion (p. ej. un mock en tests) no devuelva una
# instancia vieja. Cargar el ONNX en cada llamada costaba ~13 s en frio.
_MODEL_CACHE: dict[tuple, object] = {}
_MODEL_LOCK = threading.Lock()


def _cached_model(kind: str, cls: type, model: str):
    key = (kind, cls, model)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(key)
        if cached is None:
            cached = cls(model)
            _MODEL_CACHE[key] = cached
        return cached


def clear_model_cache() -> None:
    with _MODEL_LOCK:
        _MODEL_CACHE.clear()


class FastembedUnavailable(RuntimeError):
    """fastembed no esta instalado o no pudo cargarse (fallback a denso-only)."""


def fastembed_available() -> bool:
    """Sonda de disponibilidad sin cargar modelos (barata, sin efectos)."""
    try:
        import fastembed  # noqa: F401
    except Exception:
        return False
    return True


def embed_dense(
    texts: list[str],
    model: str = DEFAULT_DENSE_MODEL,
    batch_size: int = 5,
) -> list[list[float]]:
    """Embeddings densos normalizados via fastembed (ONNX CPU).

    Lanza ``FastembedUnavailable`` si la dependencia falta, o el error
    original si el modelo falla (el llamador decide degradar).
    Procesa en lotes configurables (por defecto 5 fragmentos, VAL-PERF-005).
    """
    try:
        from fastembed import TextEmbedding
    except Exception as exc:
        raise FastembedUnavailable(
            "fastembed is not installed; dense embeddings unavailable "
            f"(model={model!r}). Install fastembed to enable the ONNX backend."
        ) from exc
    embedding = _cached_model("dense", TextEmbedding, model)
    return [list(vector) for vector in embedding.embed(texts, batch_size=batch_size)]


@dataclass(frozen=True)
class SparseEmbedding:
    """Sparse embedding en formato Qdrant (indices + valores)."""

    indices: list[int]
    values: list[float]


def embed_sparse(
    texts: list[str], model: str = DEFAULT_SPARSE_MODEL
) -> list[SparseEmbedding]:
    """Embeddings sparse (BM25 por defecto) via fastembed.

    Lanza ``FastembedUnavailable`` si la dependencia falta.
    """
    try:
        from fastembed import SparseTextEmbedding
    except Exception as exc:
        raise FastembedUnavailable(
            "fastembed is not installed; sparse embeddings unavailable "
            f"(model={model!r}). Hybrid search degrades to dense-only."
        ) from exc
    embedding = _cached_model("sparse", SparseTextEmbedding, model)
    return [
        SparseEmbedding(indices=list(vector.indices), values=list(vector.values))
        for vector in embedding.embed(texts)
    ]


def to_qdrant_sparse(vector: SparseEmbedding):
    """Convierte a ``qdrant_client.models.SparseVector`` (import perezoso)."""
    from qdrant_client.models import SparseVector

    return SparseVector(indices=vector.indices, values=vector.values)


def hybrid_point_vector(
    dense: list[float],
    sparse: SparseEmbedding | None,
    sparse_name: str = DEFAULT_SPARSE_VECTOR_NAME,
) -> list[float] | dict:
    """Vector de punto Qdrant: lista densa (compat historica) o dict hibrido.

    Con sparse activo usa forma dict ``{"": denso, <sparse_name>: sparse}``
    sobre la misma coleccion (denso anonimo + sparse nombrado), sin recrear
    nada. Sin sparse devuelve la lista tal cual (byte-identico a antes).
    """
    if sparse is None:
        return dense
    return {DEFAULT_DENSE_VECTOR_NAME: dense, sparse_name: to_qdrant_sparse(sparse)}


@dataclass
class RankedId:
    """Un hit identificado por su point_id, con score crudo de su rama."""

    point_id: str
    score: float


@dataclass
class FusedHit:
    """Resultado de la fusion RRF con trazabilidad por rama."""

    point_id: str
    fused_score: float
    dense_score: float | None = None
    sparse_score: float | None = None
    dense_rank: int | None = None
    sparse_rank: int | None = None


def rrf_fuse(
    dense: list[RankedId],
    sparse: list[RankedId],
    *,
    k: int = DEFAULT_RRF_K,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
) -> list[FusedHit]:
    """Fusion Reciprocal Rank (rank 1-based): ``w / (k + rank)`` por rama.

    Pura y determinista: a igualdad de pesos y ranks empatados, desempata
    por point_id para un orden total estable. Los ids que solo aparecen en
    una rama conservan su contribucion parcial (score None en la otra).
    """
    fused: dict[str, FusedHit] = {}
    for rank, hit in enumerate(dense, start=1):
        entry = fused.setdefault(hit.point_id, FusedHit(point_id=hit.point_id, fused_score=0.0))
        entry.fused_score += dense_weight / (k + rank)
        entry.dense_score = hit.score
        entry.dense_rank = rank
    for rank, hit in enumerate(sparse, start=1):
        entry = fused.setdefault(hit.point_id, FusedHit(point_id=hit.point_id, fused_score=0.0))
        entry.fused_score += sparse_weight / (k + rank)
        entry.sparse_score = hit.score
        entry.sparse_rank = rank
    ordered = sorted(fused.values(), key=lambda h: (-h.fused_score, h.point_id))
    return ordered


def prefetch_limit(limit: int) -> int:
    """Sobremuestreo por rama antes de fusionar (minimo 30, x3 del limit)."""
    return max(int(limit) * PREFETCH_MULTIPLIER, PREFETCH_MINIMUM)


def tenant_filter(tenant_id: int, ticker: str | None = None):
    """Filtro Qdrant tenant (+ticker opcional). Mismo contrato que rag.py."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    conditions = []
    if ticker:
        conditions.append(FieldCondition(key="ticker", match=MatchValue(value=ticker)))
    conditions.append(FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)))
    return Filter(must=conditions) if conditions else None


def collection_has_sparse(client, collection_name: str, sparse_name: str) -> bool:
    """True si la coleccion ya expone el indice sparse (False ante error)."""
    try:
        info = client.get_collection(collection_name)
        sparse_vectors = (info.config.params.sparse_vectors or {}) if info.config and info.config.params else {}
        return sparse_name in sparse_vectors
    except Exception:
        return False


def ensure_sparse_vector(client, collection_name: str, sparse_name: str) -> bool:
    """Anade el indice sparse a una coleccion existente (no destructivo).

    Devuelve False si el servidor no lo soporta: el llamador degrada a
    denso-only. Nunca lanza.
    """
    try:
        from qdrant_client.models import SparseVectorParams

        client.update_collection(
            collection_name,
            sparse_vectors_config={sparse_name: SparseVectorParams()},
        )
        return True
    except Exception as exc:
        logger.warning("Could not enable sparse index %r: %s: %s", sparse_name, type(exc).__name__, exc)
        return False


def sparse_search_points(
    client,
    collection_name: str,
    query_sparse,
    *,
    sparse_name: str = DEFAULT_SPARSE_VECTOR_NAME,
    query_filter=None,
    limit: int = 30,
):
    """Busqueda sparse contra el indice nombrado (propaga errores al llamador)."""
    # query_points (search/NamedSparseVector se eliminaron en qdrant-client 1.16+).
    return client.query_points(
        collection_name=collection_name,
        query=query_sparse,
        using=sparse_name,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
    ).points


@dataclass
class HybridScores:
    """Trazabilidad de la fusion para el campo aditivo ``scores``."""

    dense: float | None = None
    sparse: float | None = None
    rrf: float = 0.0


@dataclass
class ScoredPayload:
    """Hit fusionado con payload Qdrant listo para mapear a dict de rag.py."""

    point_id: str
    payload: dict = field(default_factory=dict)
    scores: HybridScores = field(default_factory=HybridScores)


def warm_models(
    dense_model: str = DEFAULT_DENSE_MODEL, sparse_model: str | None = None
) -> bool:
    """Precarga los modelos para que la primera busqueda no pague la carga.

    Fail-open: nunca lanza; devuelve True si el denso quedo listo.
    """
    try:
        embed_dense(["warmup"], dense_model)
    except Exception as exc:  # noqa: BLE001 - el warmup jamas rompe el arranque
        logger.warning("embedder warmup skipped (%s: %s)", type(exc).__name__, exc)
        return False
    if sparse_model:
        try:
            embed_sparse(["warmup"], sparse_model)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sparse warmup skipped (%s: %s)", type(exc).__name__, exc)
    return True
