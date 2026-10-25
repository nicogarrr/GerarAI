"""Coleccion Qdrant del conocimiento: hijos con vector denso + sparse BM25."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.services.hybrid_retrieval import SparseEmbedding

DENSE_NAME = "dense"
SPARSE_NAME = "bm25"


@dataclass(frozen=True)
class SearchFilters:
    """Filtros de consulta. ``corpus`` por defecto = solo conocimiento atemporal.

    Los datos financieros fechados no se mezclan con cartas/libros salvo que se
    pidan expresamente (``corpus="any"`` o ``"dated"``).
    """

    corpus: str = "evergreen"  # evergreen | dated | any
    authors: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    doc_types: tuple[str, ...] = ()
    source_ids: tuple[int, ...] = ()
    published_from: date | None = None
    published_to: date | None = None
    as_of_from: date | None = None
    as_of_to: date | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def build_filter(tenant_id: int | None, filters: SearchFilters):
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, Range

    must: Any = (
        [FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))]
        if (tenant_id is not None)
        else []
    )
    if filters.corpus not in ("evergreen", "dated", "any"):
        raise ValueError("corpus must be evergreen, dated or any")
    if filters.corpus != "any":
        must.append(FieldCondition(key="corpus", match=MatchValue(value=filters.corpus)))
    if filters.authors:
        must.append(
            FieldCondition(key="author_key", match=MatchAny(any=[a.strip().lower() for a in filters.authors]))
        )
    if filters.languages:
        must.append(FieldCondition(key="language", match=MatchAny(any=list(filters.languages))))
    if filters.doc_types:
        must.append(FieldCondition(key="doc_type", match=MatchAny(any=list(filters.doc_types))))
    if filters.source_ids:
        must.append(FieldCondition(key="source_id", match=MatchAny(any=list(filters.source_ids))))
    if filters.published_from or filters.published_to:
        must.append(
            FieldCondition(
                key="published_ord",
                range=Range(
                    gte=filters.published_from.toordinal() if filters.published_from else None,
                    lte=filters.published_to.toordinal() if filters.published_to else None,
                ),
            )
        )
    if filters.as_of_from or filters.as_of_to:
        must.append(
            FieldCondition(
                key="as_of_ord",
                range=Range(
                    gte=filters.as_of_from.toordinal() if filters.as_of_from else None,
                    lte=filters.as_of_to.toordinal() if filters.as_of_to else None,
                ),
            )
        )
    return Filter(must=must)


class CollectionConfigError(ValueError):
    """La coleccion existe con otra geometria: reintentar no cambia nada."""


class KnowledgeStore:
    def __init__(self, client: Any, collection: str, dims: int = 384) -> None:
        self.client = client
        self.collection = collection
        self.dims = dims

    def ensure_collection(self) -> None:
        from qdrant_client.models import (
            Distance,
            Modifier,
            PayloadSchemaType,
            SparseVectorParams,
            VectorParams,
        )

        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection in existing:
            size = self.client.get_collection(self.collection).config.params.vectors[DENSE_NAME].size
            if size != self.dims:
                raise CollectionConfigError(
                    f"la coleccion {self.collection!r} existe con {size} dims y la configuracion "
                    f"pide {self.dims}: apunta KNOWLEDGE_RAG_COLLECTION a una coleccion nueva "
                    f"(o vuelve al modelo anterior); mezclar geometrias corrompe la busqueda"
                )
            return
        self.client.create_collection(
            self.collection,
            vectors_config={DENSE_NAME: VectorParams(size=self.dims, distance=Distance.COSINE)},
            sparse_vectors_config={SPARSE_NAME: SparseVectorParams(modifier=Modifier.IDF)},
        )
        indexes = {
            "tenant_id": PayloadSchemaType.INTEGER,
            "source_id": PayloadSchemaType.INTEGER,
            "published_ord": PayloadSchemaType.INTEGER,
            "as_of_ord": PayloadSchemaType.INTEGER,
            "author_key": PayloadSchemaType.KEYWORD,
            "language": PayloadSchemaType.KEYWORD,
            "doc_type": PayloadSchemaType.KEYWORD,
            "corpus": PayloadSchemaType.KEYWORD,
        }
        for key, schema in indexes.items():
            self.client.create_payload_index(self.collection, field_name=key, field_schema=schema)

    def upsert(
        self,
        ids: list[str],
        dense: list[list[float]],
        sparse: list[SparseEmbedding],
        payloads: list[dict[str, Any]],
    ) -> None:
        from qdrant_client.models import PointStruct, SparseVector

        points = [
            PointStruct(
                id=pid,
                vector={
                    DENSE_NAME: d,
                    SPARSE_NAME: SparseVector(indices=s.indices, values=s.values),
                },
                payload=p,
            )
            for pid, d, s, p in zip(ids, dense, sparse, payloads, strict=True)
        ]
        self.client.upsert(self.collection, points=points, wait=True)

    def delete_source(self, tenant_id: int | None, source_id: int) -> None:
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

        must: Any = [FieldCondition(key="source_id", match=MatchValue(value=source_id))]
        if tenant_id is not None:
            must.append(FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)))
        self.client.delete(
            self.collection, points_selector=FilterSelector(filter=Filter(must=must)), wait=True
        )

    def delete_tenant(self, tenant_id: int) -> int:
        """Borra todos los puntos del tenant en esta coleccion (idempotente).

        No crea la coleccion si no existe. Devuelve 1 si limpio una coleccion
        existente y 0 si no habia nada que limpiar; un fallo de Qdrant se
        propaga para que el borrado de cuenta no publique exito parcial.
        """
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection not in existing:
            return 0
        self.client.delete(
            self.collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="tenant_id", match=MatchValue(value=tenant_id)
                        )
                    ]
                )
            ),
            wait=True,
        )
        return 1

    def search_dense(self, vector: list[float], query_filter: Any, limit: int) -> list[Any]:
        return list(
            self.client.query_points(
                self.collection,
                query=vector,
                using=DENSE_NAME,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            ).points
        )

    def search_sparse(self, vector: SparseEmbedding, query_filter: Any, limit: int) -> list[Any]:
        from qdrant_client.models import SparseVector

        return list(
            self.client.query_points(
                self.collection,
                query=SparseVector(indices=vector.indices, values=vector.values),
                using=SPARSE_NAME,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            ).points
        )
