import logging
import threading

from qdrant_client import QdrantClient

from app.core.config import get_settings
from app.core.errors import redact_secrets as _redact_core
from app.llm.base import redact_secrets as _redact_llm

logger = logging.getLogger(__name__)


def redact_secrets(text: str) -> str:
    """Compone ambos redactores: userinfo/password= (core) + Bearer/JSON/token (llm)."""
    return _redact_core(_redact_llm(text))


_QDRANT_CLIENT_POOL: dict[str, QdrantClient] = {}
_QDRANT_POOL_LOCK = threading.Lock()


def get_qdrant_client(url: str) -> QdrantClient:
    """Pool de conexiones thread-safe para reutilizar clientes Qdrant sin reconexiones repetidas.

    Fulfills: VAL-PERF-005
    """
    cached = _QDRANT_CLIENT_POOL.get(url)
    if cached is not None:
        return cached
    with _QDRANT_POOL_LOCK:
        if url not in _QDRANT_CLIENT_POOL:
            _QDRANT_CLIENT_POOL[url] = QdrantClient(url=url)
        return _QDRANT_CLIENT_POOL[url]


def clear_qdrant_pool() -> None:
    """Limpia el pool de conexiones (para pruebas y reinicios)."""
    with _QDRANT_POOL_LOCK:
        _QDRANT_CLIENT_POOL.clear()


class RAGIndex:
    collection_name = "portfolio_research_documents"
    vector_size = 384

    def __init__(self) -> None:
        self.settings = get_settings()

    def client(self) -> QdrantClient:
        return get_qdrant_client(self.settings.qdrant_url)

    def _setting(self, name: str, default):
        return getattr(self.settings, name, default)

    def _collection(self) -> str:
        """Coleccion efectiva: override opt-in o la historica (compat)."""
        return self._setting("rag_collection", None) or self.collection_name

    def _dims(self) -> int:
        return int(self._setting("rag_dense_dims", self.vector_size) or self.vector_size)

    def _hybrid_wanted(self, hybrid: bool | None) -> bool:
        if hybrid is not None:
            return bool(hybrid)
        return bool(self._setting("rag_hybrid_enabled", False))

    _st_model = None
    _st_lock = threading.Lock()

    def _embedder(self):
        return type(self).warm_fallback()

    @classmethod
    def warm_fallback(cls):
        """Carga (una vez por proceso) el modelo ST de fallback y lo devuelve."""
        if cls._st_model is None:
            with cls._st_lock:
                if cls._st_model is None:
                    from sentence_transformers import SentenceTransformer

                    cls._st_model = SentenceTransformer("all-MiniLM-L6-v2")
        return cls._st_model

    def _dense_vectors(self, texts: list[str]) -> list[list[float]]:
        """Vectores densos normalizados: fastembed (ONNX) primero, ST fallback.

        Mismo modelo/dims/espacio que produccion (coseno ~1.0 medido entre
        ambos backends): cambiar de backend no invalida el indice.
        """
        backend = str(self._setting("rag_embedding_backend", "fastembed") or "fastembed")
        model = str(
            self._setting("rag_dense_model", "sentence-transformers/all-MiniLM-L6-v2")
            or "sentence-transformers/all-MiniLM-L6-v2"
        )
        if backend.strip().lower() != "sentence-transformers":
            try:
                from app.services.hybrid_retrieval import embed_dense

                return embed_dense(texts, model)
            except Exception as exc:
                logger.warning(
                    "fastembed dense backend unavailable (%s: %s); falling back to sentence-transformers",
                    type(exc).__name__,
                    redact_secrets(str(exc)),
                )
        return self._embedder().encode(texts, normalize_embeddings=True).tolist()

    def _sparse_embeddings(self, texts: list[str]):
        """Embeddings sparse (BM25) o None si el hibrido esta off/no disponible."""
        from app.services.hybrid_retrieval import FastembedUnavailable, embed_sparse

        model = str(self._setting("rag_sparse_model", "Qdrant/bm25") or "Qdrant/bm25")
        try:
            return embed_sparse(texts, model)
        except FastembedUnavailable as exc:
            logger.warning(
                "Hybrid sparse disabled (fastembed missing): %s; continuing dense-only",
                redact_secrets(str(exc)),
            )
            return None
        except Exception as exc:
            logger.warning(
                "Sparse embedding failed (%s: %s); continuing dense-only",
                type(exc).__name__,
                redact_secrets(str(exc)),
            )
            return None

    def _ensure_collection(self, client: QdrantClient) -> None:
        from qdrant_client.models import Distance, VectorParams
        collection = self._collection()
        collections = [c.name for c in client.get_collections().collections]
        if collection not in collections:
            kwargs: dict = {}
            if self._hybrid_wanted(None):
                from qdrant_client.models import SparseVectorParams

                from app.services.hybrid_retrieval import DEFAULT_SPARSE_VECTOR_NAME

                sparse_name = str(
                    self._setting("rag_sparse_vector_name", DEFAULT_SPARSE_VECTOR_NAME)
                    or DEFAULT_SPARSE_VECTOR_NAME
                )
                kwargs["sparse_vectors_config"] = {sparse_name: SparseVectorParams()}
            client.create_collection(
                collection,
                vectors_config=VectorParams(size=self._dims(), distance=Distance.COSINE),
                **kwargs,
            )
            self._ensure_payload_indexes(client, collection)
            return
        self._ensure_payload_indexes(client, collection)
        if self._hybrid_wanted(None):
            from app.services import hybrid_retrieval as _hybrid

            sparse_name = str(
                self._setting("rag_sparse_vector_name", _hybrid.DEFAULT_SPARSE_VECTOR_NAME)
                or _hybrid.DEFAULT_SPARSE_VECTOR_NAME
            )
            if not _hybrid.collection_has_sparse(client, collection, sparse_name):
                _hybrid.ensure_sparse_vector(client, collection, sparse_name)

    _PAYLOAD_INDEXES = (("tenant_id", "integer"), ("ticker", "keyword"), ("entity_type", "keyword"))

    def _ensure_payload_indexes(self, client: QdrantClient, collection: str) -> None:
        """Indices de payload de los campos que filtra la busqueda.

        Sin ellos cada busqueda filtrada recorre los payloads: medido 25-oct en
        prod (176k puntos) 5-30 s por consulta y el cliente cortaba a ~5 s;
        con indices 0,01 s. Idempotente (solo crea los que faltan) y nunca
        rompe la busqueda: ante fallo registra y sigue.
        """
        try:
            from qdrant_client.models import PayloadSchemaType

            existing = set((client.get_collection(collection).payload_schema or {}).keys())
            for field, kind in self._PAYLOAD_INDEXES:
                if field not in existing:
                    client.create_payload_index(
                        collection, field_name=field, field_schema=PayloadSchemaType(kind), wait=True
                    )
        except Exception as exc:
            logger.warning("RAG payload index check failed: %s", type(exc).__name__)

    def ingest_document(self, db, document) -> dict:
        import uuid

        from qdrant_client.models import PointStruct
        from sqlalchemy import select

        from app.models import DocumentChunk

        tenant_id = db.info.get("tenant_id")
        if tenant_id is None or document.tenant_id != tenant_id:
            raise ValueError("Tenant context is required to index a document")

        chunks = list(db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.chunk_index)
        ).all())

        if not chunks:
            return {"chunks_indexed": 0, "collection": self._collection()}

        texts = [c.text for c in chunks]
        vectors = self._dense_vectors(texts)
        expected_dims = self._dims()
        if any(len(vector) != expected_dims for vector in vectors):
            return {
                "chunks_indexed": 0,
                "error": (
                    f"Dense embedding dims mismatch: got {len(vectors[0]) if vectors else 0}, "
                    f"collection expects {expected_dims} "
                    "(rag_dense_dims/rag_collection opt-in + rebuild_tenant required)"
                ),
                "collection": self._collection(),
            }

        hybrid = self._hybrid_wanted(None)
        sparse_vectors = self._sparse_embeddings(texts) if hybrid else None
        sparse_skipped = bool(hybrid and sparse_vectors is None)
        if hybrid and sparse_vectors is not None:
            from app.services import hybrid_retrieval as _hybrid

            sparse_name = str(
                self._setting("rag_sparse_vector_name", _hybrid.DEFAULT_SPARSE_VECTOR_NAME)
                or _hybrid.DEFAULT_SPARSE_VECTOR_NAME
            )
        else:
            sparse_name = ""

        ticker = None
        if document.company_id:
            from app.models import Company
            company = db.get(Company, document.company_id)
            ticker = company.ticker if company else None

        points = []
        for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
            if chunk.qdrant_point_id:
                point_id = chunk.qdrant_point_id
            else:
                point_id = str(uuid.uuid4())
                chunk.qdrant_point_id = point_id
            if sparse_vectors is not None:
                from app.services.hybrid_retrieval import hybrid_point_vector

                point_vector = hybrid_point_vector(vector, sparse_vectors[index], sparse_name)
            else:
                point_vector = vector
            points.append(PointStruct(
                id=point_id,
                vector=point_vector,
                payload={
                    "text": chunk.text,
                    "ticker": ticker,
                    "document_id": document.id,
                    "chunk_index": chunk.chunk_index,
                    "entity_type": "document_chunk",
                    "entity_id": chunk.id,
                    "source_type": document.source_type,
                    "title": document.title,
                    "tenant_id": tenant_id,
                },
            ))

        try:
            client = self.client()
            self._ensure_collection(client)
            client.upsert(collection_name=self._collection(), points=points)
            db.commit()
        except Exception as exc:
            return {"chunks_indexed": 0, "error": redact_secrets(str(exc)), "collection": self._collection()}

        result: dict = {"chunks_indexed": len(points), "collection": self._collection()}
        if sparse_skipped:
            result["sparse_skipped"] = True
        return result

    def ingest_knowledge_document(self, db, document) -> dict:
        import uuid

        from qdrant_client.models import PointStruct
        from sqlalchemy import select

        from app.models import KnowledgeChunk

        tenant_id = db.info.get("tenant_id")
        if tenant_id is None or document.tenant_id != tenant_id:
            raise ValueError("Tenant context is required to index knowledge")
        chunks = list(
            db.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.knowledge_document_id == document.id)
                .order_by(KnowledgeChunk.chunk_index)
            ).all()
        )
        if not chunks:
            return {"chunks_indexed": 0, "collection": self._collection()}
        vectors = self._dense_vectors([chunk.content for chunk in chunks])
        expected_dims = self._dims()
        if any(len(vector) != expected_dims for vector in vectors):
            return {
                "chunks_indexed": 0,
                "error": (
                    f"Dense embedding dims mismatch: got {len(vectors[0]) if vectors else 0}, "
                    f"collection expects {expected_dims} "
                    "(rag_dense_dims/rag_collection opt-in + rebuild_tenant required)"
                ),
                "collection": self._collection(),
            }
        hybrid = self._hybrid_wanted(None)
        sparse_vectors = self._sparse_embeddings([chunk.content for chunk in chunks]) if hybrid else None
        sparse_skipped = bool(hybrid and sparse_vectors is None)
        if hybrid and sparse_vectors is not None:
            from app.services import hybrid_retrieval as _hybrid

            sparse_name = str(
                self._setting("rag_sparse_vector_name", _hybrid.DEFAULT_SPARSE_VECTOR_NAME)
                or _hybrid.DEFAULT_SPARSE_VECTOR_NAME
            )
        else:
            sparse_name = ""
        points = []
        for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
            point_id = chunk.qdrant_point_id or str(uuid.uuid4())
            chunk.qdrant_point_id = point_id
            if sparse_vectors is not None:
                from app.services.hybrid_retrieval import hybrid_point_vector

                point_vector = hybrid_point_vector(vector, sparse_vectors[index], sparse_name)
            else:
                point_vector = vector
            points.append(
                PointStruct(
                    id=point_id,
                    vector=point_vector,
                    payload={
                        "text": chunk.content,
                        "title": document.title,
                        "source_type": document.document_type,
                        "knowledge_document_id": document.id,
                        "collection_id": document.collection_id,
                        "chunk_index": chunk.chunk_index,
                        "page_number": chunk.page_number,
                        "entity_type": "knowledge_chunk",
                        "entity_id": chunk.id,
                        "tenant_id": tenant_id,
                    },
                )
            )
        try:
            client = self.client()
            self._ensure_collection(client)
            client.upsert(collection_name=self._collection(), points=points)
            db.commit()
        except Exception as exc:
            return {
                "chunks_indexed": 0,
                "error": redact_secrets(str(exc)),
                "collection": self._collection(),
            }
        result = {"chunks_indexed": len(points), "collection": self._collection()}
        if sparse_skipped:
            result["sparse_skipped"] = True
        return result

    def delete_tenant_points(self, tenant_id: int) -> int:
        """Borra todos los puntos del tenant (indice desechable, datos derivados).

        No crea la coleccion si no existe: un tenant que nunca activo la
        ingesta vectorial no debe provocar efectos laterales al borrarse. Un
        fallo de Qdrant se propaga: el llamador decide si puede publicar
        exito (borrado de cuenta) o solo registrar la incidencia (retencion).
        """
        return self._delete_points(tenant_id)

    def delete_document_points(self, tenant_id: int, document_id: int) -> int:
        """Borra los puntos de un documento financiero concreto."""
        return self._delete_points(tenant_id, ("document_id", document_id))

    def delete_knowledge_document_points(
        self, tenant_id: int, knowledge_document_id: int
    ) -> int:
        """Borra los puntos de un documento de la biblioteca de conocimiento."""
        return self._delete_points(
            tenant_id, ("knowledge_document_id", knowledge_document_id)
        )

    def _delete_points(
        self, tenant_id: int, extra: tuple[str, int] | None = None
    ) -> int:
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            FilterSelector,
            MatchValue,
        )

        client = self.client()
        collection = self._collection()
        if not client.collection_exists(collection):
            return 0
        must = [
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=tenant_id),
            )
        ]
        if extra is not None:
            key, value = extra
            must.append(
                FieldCondition(key=key, match=MatchValue(value=value))
            )
        client.delete(
            collection_name=collection,
            points_selector=FilterSelector(filter=Filter(must=must)),
            wait=True,
        )
        return 1

    def rebuild_tenant(self, db) -> dict:
        """Recreate one tenant's disposable Qdrant index from PostgreSQL chunks."""
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            FilterSelector,
            MatchValue,
        )
        from sqlalchemy import select

        from app.models import Document, KnowledgeDocument

        tenant_id = db.info.get("tenant_id")
        if tenant_id is None:
            raise ValueError("Tenant context is required to rebuild the vector index")

        client = self.client()
        self._ensure_collection(client)
        client.delete(
            collection_name=self._collection(),
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="tenant_id",
                            match=MatchValue(value=tenant_id),
                        )
                    ]
                )
            ),
            wait=True,
        )

        documents = list(
            db.scalars(
                select(Document)
                .where(Document.tenant_id == tenant_id)
                .order_by(Document.id)
            ).all()
        )
        indexed = 0
        errors: list[dict] = []
        for document in documents:
            result = self.ingest_document(db, document)
            indexed += int(result.get("chunks_indexed", 0))
            if result.get("error"):
                errors.append({"document_id": document.id, "error": result["error"]})
        knowledge_documents = list(
            db.scalars(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.tenant_id == tenant_id)
                .order_by(KnowledgeDocument.id)
            ).all()
        )
        for document in knowledge_documents:
            result = self.ingest_knowledge_document(db, document)
            indexed += int(result.get("chunks_indexed", 0))
            if result.get("error"):
                errors.append(
                    {"knowledge_document_id": document.id, "error": result["error"]}
                )
        return {
            "tenant_id": tenant_id,
            "documents": len(documents),
            "knowledge_documents": len(knowledge_documents),
            "chunks_indexed": indexed,
            "errors": errors,
            "collection": self._collection(),
        }

    @staticmethod
    def _row(point, score: float, scores: dict | None = None) -> dict:
        """Mapea un ScoredPoint al dict de contrato (estable desde el origen)."""
        row = {
            "text": point.payload.get("text", ""),
            "ticker": point.payload.get("ticker"),
            "document_id": point.payload.get("document_id"),
            "knowledge_document_id": point.payload.get("knowledge_document_id"),
            "collection_id": point.payload.get("collection_id"),
            "page_number": point.payload.get("page_number"),
            "source_type": point.payload.get("source_type"),
            "title": point.payload.get("title"),
            "score": score,
            "point_id": point.id,
            "entity_type": point.payload.get("entity_type"),
            "entity_id": point.payload.get("entity_id"),
            "chunk_index": point.payload.get("chunk_index"),
        }
        if scores is not None:
            row["scores"] = scores
        return row

    def _query_filter(self, ticker: str | None, tenant_id: int, entity_type: str | None = None):
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        conditions = []
        if ticker:
            conditions.append(
                FieldCondition(
                    key="ticker", match=MatchValue(value=ticker)
                )
            )
        conditions.append(
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=tenant_id),
            )
        )
        if entity_type:
            conditions.append(
                FieldCondition(key="entity_type", match=MatchValue(value=entity_type))
            )
        return Filter(must=conditions) if conditions else None

    def search(
        self,
        query: str,
        ticker: str | None = None,
        limit: int = 5,
        tenant_id: int | None = None,
        hybrid: bool | None = None,
        *,
        entity_type: str | None = None,
    ) -> list[dict]:
        """Busqueda semantica densa (default, contrato intacto) o hibrida RRF.

        ``hybrid=None`` respeta ``rag_hybrid_enabled``; ``hybrid=False``
        fuerza el path denso historico (sin campo ``scores``). En modo
        hibrido cada hit suma ``scores`` = {dense, sparse, rrf} y ``score``
        es la fusion RRF. Ante cualquier fallo devuelve [] con warning.
        """
        if tenant_id is None:
            return []
        try:
            vector = self._dense_vectors([query])[0]
            client = self.client()
            self._ensure_collection(client)
            query_filter = (
                self._query_filter(ticker, tenant_id, entity_type)
                if entity_type
                else self._query_filter(ticker, tenant_id)
            )
            if not self._hybrid_wanted(hybrid):
                results = client.query_points(
                    collection_name=self._collection(),
                    query=vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                ).points
                return [self._row(r, r.score) for r in results]
            return self._hybrid_search(client, query, vector, query_filter, limit)
        except Exception as exc:
            # Fallar en silencio ocultaba que la busqueda semantica no
            # funcionaba (embedder o Qdrant caidos): se registra la causa.
            logger.warning("RAG search failed: %s: %s", type(exc).__name__, redact_secrets(str(exc)))
            return []

    def _hybrid_search(self, client, query: str, dense_vector: list[float], query_filter, limit: int) -> list[dict]:
        """Denso + BM25 con fusion RRF (lado cliente). Degrada a denso-only."""
        from app.services import hybrid_retrieval as _hybrid

        sparse_vectors = self._sparse_embeddings([query])
        if sparse_vectors is None:
            results = client.query_points(
                collection_name=self._collection(),
                query=dense_vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            ).points
            return [self._row(r, r.score) for r in results]

        fetch = _hybrid.prefetch_limit(limit)
        dense_hits = client.query_points(
            collection_name=self._collection(),
            query=dense_vector,
            query_filter=query_filter,
            limit=fetch,
            with_payload=True,
        ).points
        sparse_name = str(
            self._setting("rag_sparse_vector_name", _hybrid.DEFAULT_SPARSE_VECTOR_NAME)
            or _hybrid.DEFAULT_SPARSE_VECTOR_NAME
        )
        try:
            sparse_hits = _hybrid.sparse_search_points(
                client,
                self._collection(),
                _hybrid.to_qdrant_sparse(sparse_vectors[0]),
                sparse_name=sparse_name,
                query_filter=query_filter,
                limit=fetch,
            )
        except Exception as exc:
            logger.warning(
                "Hybrid sparse search failed (%s: %s); continuing dense-only",
                type(exc).__name__,
                redact_secrets(str(exc)),
            )
            return [self._row(r, r.score) for r in dense_hits[:limit]]

        payloads: dict[str, object] = {}
        for point in list(dense_hits) + list(sparse_hits):
            payloads.setdefault(str(point.id), point)
        fused = _hybrid.rrf_fuse(
            [_hybrid.RankedId(str(p.id), float(p.score)) for p in dense_hits],
            [_hybrid.RankedId(str(p.id), float(p.score)) for p in sparse_hits],
            k=int(self._setting("rag_rrf_k", _hybrid.DEFAULT_RRF_K) or _hybrid.DEFAULT_RRF_K),
            dense_weight=float(self._setting("rag_dense_weight", 1.0)),
            sparse_weight=float(self._setting("rag_sparse_weight", 1.0)),
        )
        rows = []
        for hit in fused[:limit]:
            point = payloads[hit.point_id]
            rows.append(self._row(
                point,
                hit.fused_score,
                {"dense": hit.dense_score, "sparse": hit.sparse_score, "rrf": hit.fused_score},
            ))
        return rows

    def status(self) -> dict:
        try:
            collections = self.client().get_collections()
            return {
                "configured": True,
                "collections": [c.name for c in collections.collections],
                "collection": self._collection(),
                "embedding_backend": self._setting("rag_embedding_backend", "fastembed"),
                "dense_model": self._setting(
                    "rag_dense_model", "sentence-transformers/all-MiniLM-L6-v2"
                ),
                "hybrid_enabled": self._hybrid_wanted(None),
            }
        except Exception as exc:
            return {"configured": False, "error": redact_secrets(str(exc))}
