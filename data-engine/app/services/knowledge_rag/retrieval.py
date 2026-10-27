"""Consulta: denso + sparse -> RRF -> (reranker) -> padres -> citas verificadas."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeRelationship, NodeWithScore, QueryBundle, RelatedNodeInfo, TextNode

from app.services.hybrid_retrieval import FusedHit, RankedId, rrf_fuse
from app.services.knowledge_rag.citations import Citation, format_context, verify_citation
from app.services.knowledge_rag.embedding import Embedder
from app.services.knowledge_rag.store import KnowledgeStore, SearchFilters, build_filter

# parent_id -> (texto del padre, sha256 del padre)
ParentResolver = Callable[[Sequence[str]], dict[str, tuple[str, str]]]


@dataclass
class SearchResult:
    query: str
    citations: list[Citation]
    context: str
    dropped_unverified: int = 0
    candidates: int = 0
    notes: list[str] = field(default_factory=list)
    # Variantes de la consulta usadas ademas de la original (p. ej. la
    # traduccion ES->EN de query_translation). Vacio = solo la original.
    query_variants: list[str] = field(default_factory=list)


def _fuse_query_variants(per_query: list[list[FusedHit]], *, k: int) -> list[FusedHit]:
    """Una variante: la fusion denso+sparse tal cual. Varias (original +
    traduccion): RRF de segundo nivel sobre los rankings por variante, misma
    formula 1/(k+rank). La trazabilidad denso/sparse la conserva la primera
    variante que aporto el id (la original va primero).
    """
    if len(per_query) == 1:
        return per_query[0]
    combined: dict[str, FusedHit] = {}
    for ranking in per_query:
        for rank, hit in enumerate(ranking, start=1):
            entry = combined.setdefault(hit.point_id, FusedHit(point_id=hit.point_id, fused_score=0.0))
            entry.fused_score += 1.0 / (k + rank)
            if entry.dense_rank is None and hit.dense_rank is not None:
                entry.dense_rank, entry.dense_score = hit.dense_rank, hit.dense_score
            if entry.sparse_rank is None and hit.sparse_rank is not None:
                entry.sparse_rank, entry.sparse_score = hit.sparse_rank, hit.sparse_score
    return sorted(combined.values(), key=lambda h: (-h.fused_score, h.point_id))


def _overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["parent_id"] != b["parent_id"]:
        return False
    lo = max(a["char_start"], b["char_start"])
    hi = min(a["char_end"], b["char_end"])
    shorter = min(a["char_end"] - a["char_start"], b["char_end"] - b["char_start"]) or 1
    return (hi - lo) / shorter > 0.5


def search_knowledge(
    query: str,
    *,
    tenant_id: int | None,
    store: KnowledgeStore,
    embedder: Embedder,
    resolve_parents: ParentResolver,
    filters: SearchFilters | None = None,
    top_k: int = 6,
    candidates: int = 40,
    postprocessors: Sequence[BaseNodePostprocessor] = (),
    rrf_k: int = 60,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
    query_variants: Sequence[str] = (),
) -> SearchResult:
    if not query.strip():
        raise ValueError("query is empty")
    # Original + variantes (p. ej. traduccion ES->EN), deduplicadas: cada una
    # busca en denso y sparse y los rankings se fusionan (ver _fuse_query_variants).
    queries = [query]
    for variant in query_variants:
        v = " ".join(variant.split())
        if v and v.casefold() not in {q.casefold() for q in queries}:
            queries.append(v)
    flt = build_filter(tenant_id, filters or SearchFilters())
    payloads: dict[str, dict] = {}
    per_query: list[list[FusedHit]] = []
    for q in queries:
        dense_hits = store.search_dense(embedder.dense_query(q), flt, candidates)
        sparse_hits = store.search_sparse(embedder.sparse_query(q), flt, candidates)
        payloads.update({str(h.id): dict(h.payload or {}) for h in [*dense_hits, *sparse_hits]})
        per_query.append(
            rrf_fuse(
                [RankedId(str(h.id), float(h.score)) for h in dense_hits],
                [RankedId(str(h.id), float(h.score)) for h in sparse_hits],
                k=rrf_k,
                dense_weight=dense_weight,
                sparse_weight=sparse_weight,
            )
        )
    fused = _fuse_query_variants(per_query, k=rrf_k)
    nodes: list[NodeWithScore] = []
    for hit in fused[:candidates]:
        p = payloads[hit.point_id]
        node = TextNode(
            id_=hit.point_id,
            text=p["text"],
            metadata={**p, "dense_score": hit.dense_score, "sparse_score": hit.sparse_score},
            relationships={NodeRelationship.PARENT: RelatedNodeInfo(node_id=p["parent_id"])},
            excluded_embed_metadata_keys=list(p),
            excluded_llm_metadata_keys=list(p),
        )
        nodes.append(NodeWithScore(node=node, score=hit.fused_score))
    bundle = QueryBundle(query_str=query)
    for post in postprocessors:
        nodes = post.postprocess_nodes(nodes, bundle)

    # Seleccion con relleno: si un padre no se resuelve o la cita no verifica,
    # se descarta y se sigue con el siguiente candidato hasta tener top_k citas
    # verificadas (antes se cortaba en top_k ANTES de verificar y salian menos
    # fuentes). Los padres se resuelven por lotes; en el caso normal es una
    # sola llamada con los mismos ids que antes.
    parents: dict[str, tuple[str, str]] = {}
    requested: set[str] = set()
    accepted: list[NodeWithScore] = []
    verified: list[tuple[NodeWithScore, tuple[str, str], Any]] = []
    citations: list[Citation] = []
    dropped = 0
    remaining = list(nodes)
    while remaining and len(verified) < top_k:
        batch: list[NodeWithScore] = []
        rest: list[NodeWithScore] = []
        for n in remaining:
            if len(verified) + len(batch) >= top_k:
                rest.append(n)
                continue
            if any(_overlaps(n.node.metadata, c.node.metadata) for c in accepted):
                continue
            if any(_overlaps(n.node.metadata, c.node.metadata) for c in batch):
                # Puede servir si el que solapa no llega a verificarse.
                rest.append(n)
                continue
            batch.append(n)
        remaining = rest
        if not batch:
            break
        missing = sorted(
            {n.node.metadata["parent_id"] for n in batch} - requested
        )
        if missing:
            requested.update(missing)
            parents.update(resolve_parents(missing))
        for n in batch:
            m = n.node.metadata
            parent = parents.get(m["parent_id"])
            if parent is None:
                dropped += 1
                continue
            parent_text, parent_hash = parent
            result = verify_citation(
                quote=n.node.get_content(),
                parent_text=parent_text,
                char_start=m["char_start"],
                char_end=m["char_end"],
                text_sha256=m["text_sha256"],
                parent_text_sha256=parent_hash,
            )
            if not result.ok:
                dropped += 1
                continue
            accepted.append(n)
            verified.append((n, parent, result))

    for n, (parent_text, _parent_hash), result in verified:
        m = n.node.metadata
        citations.append(
            Citation(
                number=len(citations) + 1,
                chunk_id=n.node.node_id,
                quote=n.node.get_content(),
                context=parent_text,
                parent_id=m["parent_id"],
                source_id=m["source_id"],
                source_sha256=m["source_sha256"],
                title=m["title"],
                author=m.get("author"),
                source_uri=m["source_uri"],
                language=m["language"],
                doc_type=m["doc_type"],
                corpus=m["corpus"],
                rights=m["rights"],
                published_date=m.get("published_date"),
                as_of=m.get("as_of"),
                section_path=list(m.get("section_path") or []),
                page_start=m.get("page_start"),
                page_end=m.get("page_end"),
                bboxes=list(m.get("bboxes") or []),
                char_start=m["char_start"],
                char_end=m["char_end"],
                text_sha256=m["text_sha256"],
                scores={
                    "rrf": m.get("rrf_score", n.score),
                    "dense": m.get("dense_score"),
                    "sparse": m.get("sparse_score"),
                    "rerank": m.get("rerank_score"),
                },
                verified=True,
                verification=result.checks,
            )
        )
    notes = [] if citations else ["no verified passages: answer must abstain"]
    return SearchResult(
        query=query,
        citations=citations,
        context=format_context(citations),
        dropped_unverified=dropped,
        candidates=len(nodes),
        notes=notes,
        query_variants=queries[1:],
    )
