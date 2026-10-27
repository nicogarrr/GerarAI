"""Audit #22: executable evidence for version IDs, overlap refill and ES/EN fusion.

Hermetic ranking/embedding doubles, real chunker/retrieval/citation verifier.
Not a semantic relevance evaluation with a real multilingual model.
"""
from copy import deepcopy

from app.services.knowledge_rag.chunking import ChunkConfig, chunk_document
from app.services.knowledge_rag.domain import Block, ExtractedDocument, Section
from app.services.knowledge_rag.retrieval import _overlaps, search_knowledge
from tests.knowledge_rag_helpers import FakeEmbedder, fake_count
from tests.test_knowledge_rag_refill import _Hit, _payload, _sha


def test_different_source_versions_get_distinct_parent_ids_and_do_not_overlap():
    doc = ExtractedDocument([Section(("Chapter",), [Block("Safety margin protects against investment error.", page=1)])], "fixture")
    cfg = ChunkConfig(child_max_tokens=50, child_overlap_tokens=8, parent_max_tokens=160)
    parents = []
    for version in ("v1-sha", "v2-sha"):
        p, _ = chunk_document(doc, title="Letter", source_sha256=version, count=fake_count, config=cfg,
                              id_namespace=f"1:42:{version}")
        parents.append(p[0])
    assert parents[0].id != parents[1].id
    assert not _overlaps({"parent_id": parents[0].id, "char_start": 0, "char_end": 20},
                         {"parent_id": parents[1].id, "char_start": 0, "char_end": 20})


def test_failed_overlapping_candidate_does_not_hide_valid_literal_quote():
    good = _payload(0)
    bad = deepcopy(good)
    bad["text_sha256"] = "0" * 64
    hits = [_Hit("broken", 1.0, bad), _Hit("valid", .9, good), _Hit("other", .8, _payload(1))]
    class Store:
        def search_dense(self, *args): return hits
        def search_sparse(self, *args): return hits
    parents = {f"p{i}": (_payload(i)["parent_text"], _sha(_payload(i)["parent_text"])) for i in (0,1)}
    result = search_knowledge("margen", tenant_id=1, store=Store(), embedder=FakeEmbedder(),
                              resolve_parents=lambda ids: {i: parents[i] for i in ids}, top_k=2)
    assert {c.parent_id for c in result.citations} == {"p0", "p1"}
    assert all(c.verified for c in result.citations)
    assert result.dropped_unverified == 1


def test_es_en_variants_keep_independent_sources_and_verify_each_quote():
    class Embedder(FakeEmbedder):
        def dense_query(self, text): return text
        def sparse_query(self, text): return text
    class Store:
        def search_dense(self, query, *args):
            return [_Hit("es", 1, _payload(0))] if query == "margen" else [_Hit("en", 1, _payload(1))]
        def search_sparse(self, query, *args): return self.search_dense(query)
    parents = {f"p{i}": (_payload(i)["parent_text"], _sha(_payload(i)["parent_text"])) for i in (0,1)}
    result = search_knowledge("margen", query_variants=["safety margin", "safety margin"], tenant_id=1,
                              store=Store(), embedder=Embedder(), resolve_parents=lambda ids: {i: parents[i] for i in ids}, top_k=2)
    assert {c.parent_id for c in result.citations} == {"p0", "p1"}
    assert all(c.verified for c in result.citations)
    assert result.query_variants == ["safety margin"]
