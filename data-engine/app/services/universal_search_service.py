"""Tenant-safe hybrid search across the complete investment research corpus."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CalculatedMetric,
    Claim,
    Company,
    DecisionJournalEntry,
    DecisionLesson,
    Document,
    DocumentChunk,
    FinancialFact,
    InvestmentCaseStudy,
    InvestmentPrinciple,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    ThesisSection,
)
from app.services.source_hierarchy_service import classify_source

TOKEN_RE = re.compile(r"[\w.-]+", re.UNICODE)
RRF_K = 60


def _rows(db: Session, statement: Any) -> list[tuple[Any, ...]]:
    """Filas como tuplas planas: SQLAlchemy 2.1 tipa Row por columna y pyright
    no puede desempaquetar la salida de ``_fts`` (sin anotar)."""
    return [tuple(row) for row in db.execute(statement).all()]


@dataclass
class SearchCandidate:
    key: str
    entity_type: str
    entity_id: int
    title: str
    text: str
    company_id: int | None = None
    ticker: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    collection_id: int | None = None
    collection: str | None = None
    status: str | None = None
    as_of: date | datetime | None = None
    metadata: dict[str, Any] | None = None


def _tokens(value: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(value) if len(token) > 1]


def _lexical_score(query: str, candidate: SearchCandidate) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    text = f"{candidate.title} {candidate.text}".lower()
    title = candidate.title.lower()
    matched = sum(1 for token in query_tokens if token in text)
    if not matched:
        return 0.0
    coverage = matched / len(set(query_tokens))
    frequency = sum(min(text.count(token), 5) for token in set(query_tokens))
    title_hits = sum(1 for token in set(query_tokens) if token in title)
    phrase = 1.0 if query.strip().lower() in text else 0.0
    return coverage * 4 + math.log1p(frequency) + title_hits * 0.4 + phrase * 2


class UniversalSearchService:
    """PostgreSQL FTS + optional Qdrant + RRF + deterministic reranking."""

    def search(
        self,
        db: Session,
        query: str,
        *,
        ticker: str | None = None,
        entity_types: set[str] | None = None,
        source_types: set[str] | None = None,
        collection_id: int | None = None,
        statuses: set[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 20,
        include_vector: bool = True,
    ) -> dict[str, Any]:
        tenant_id = db.info.get("tenant_id")
        if tenant_id is None:
            raise ValueError("Tenant context is required for universal search")
        query = query.strip()
        if not query:
            raise ValueError("Search query cannot be empty")
        company = None
        if ticker:
            company = db.scalar(select(Company).where(Company.ticker == ticker.strip().upper()))
            if company is None:
                return self._not_found(query, include_vector)

        candidates = self._candidates(
            db,
            query,
            company=company,
            entity_types=entity_types,
            collection_id=collection_id,
        )
        candidates = [
            item
            for item in candidates
            if self._matches_filters(
                item,
                source_types=source_types,
                statuses=statuses,
                date_from=date_from,
                date_to=date_to,
            )
        ]
        lexical = sorted(
            ((item, _lexical_score(query, item)) for item in candidates),
            key=lambda pair: pair[1],
            reverse=True,
        )
        lexical = [pair for pair in lexical if pair[1] > 0]

        vector_rows: list[dict[str, Any]] = []
        vector_status = "disabled"
        if include_vector and os.getenv("CAVAAI_ENABLE_VECTOR_SEARCH") == "1":
            vector_status = "available"
            try:
                from app.services.rag import RAGIndex

                vector_rows = RAGIndex().search(
                    query,
                    ticker=company.ticker if company else None,
                    limit=max(limit * 3, 30),
                    tenant_id=tenant_id,
                )
            except Exception as exc:  # pragma: no cover - external boundary
                vector_status = f"unavailable:{type(exc).__name__}"
                vector_rows = []

        # PostgreSQL FTS deliberately returns only lexical matches.  Hydrate
        # vector-only hits so semantic retrieval can contribute independent
        # candidates to RRF instead of merely reordering lexical matches.
        known_keys = {item.key for item in candidates}
        for item in self._hydrate_vector_candidates(
            db,
            vector_rows,
            company=company,
            entity_types=entity_types,
            collection_id=collection_id,
        ):
            if item.key in known_keys:
                continue
            if not self._matches_filters(
                item,
                source_types=source_types,
                statuses=statuses,
                date_from=date_from,
                date_to=date_to,
            ):
                continue
            candidates.append(item)
            known_keys.add(item.key)

        by_key = {item.key: item for item in candidates}
        rrf: dict[str, float] = {}
        lexical_scores: dict[str, float] = {}
        vector_scores: dict[str, float] = {}
        for rank, (item, score) in enumerate(lexical, start=1):
            rrf[item.key] = rrf.get(item.key, 0.0) + 1 / (RRF_K + rank)
            lexical_scores[item.key] = score
        for rank, row in enumerate(vector_rows, start=1):
            key = self._vector_key(row)
            if key not in by_key:
                continue
            rrf[key] = rrf.get(key, 0.0) + 1 / (RRF_K + rank)
            vector_scores[key] = float(row.get("score") or 0)

        ranked: list[tuple[float, SearchCandidate]] = []
        for key, fusion_score in rrf.items():
            item = by_key[key]
            source = classify_source(item.source_type, item.source_url)
            canonical_bonus = 0.08 if item.status in {"approved", "verified", "active"} else 0
            hierarchy_bonus = (source.trust_score / max(source.rank, 1)) * 0.12
            ranked.append((fusion_score + hierarchy_bonus + canonical_bonus, item))
        ranked.sort(
            key=lambda pair: (pair[0], lexical_scores.get(pair[1].key, 0)),
            reverse=True,
        )

        results = []
        for rerank_score, item in ranked[: max(1, min(limit, 100))]:
            tier = classify_source(item.source_type, item.source_url)
            results.append(
                {
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "title": item.title,
                    "text": item.text,
                    "ticker": item.ticker,
                    "company_id": item.company_id,
                    "collection_id": item.collection_id,
                    "collection": item.collection,
                    "status": item.status,
                    "source_type": item.source_type,
                    "source_tier": tier.key,
                    "source_trust": tier.trust_score,
                    "as_of": item.as_of,
                    "metadata": item.metadata or {},
                    "scores": {
                        "lexical": round(lexical_scores.get(item.key, 0), 8),
                        "vector": round(vector_scores.get(item.key, 0), 8),
                        "rrf": round(rrf[item.key], 8),
                        "reranker": round(rerank_score, 8),
                    },
                    "citation": f"{item.entity_type}:{item.entity_id}",
                }
            )
        return {
            "query": query,
            "filters": {
                "ticker": company.ticker if company else None,
                "entity_types": sorted(entity_types) if entity_types else [],
                "source_types": sorted(source_types) if source_types else [],
                "collection_id": collection_id,
                "statuses": sorted(statuses) if statuses else [],
                "date_from": date_from,
                "date_to": date_to,
            },
            "retrieval": {
                # Modo real: hybrid solo si el vector aportó candidatos al
                # RRF; en cualquier otro caso lexical_only honesto.
                "mode": "hybrid" if vector_scores else "lexical_only",
                "lexical_backend": (
                    "postgresql_full_text"
                    if db.bind and db.bind.dialect.name == "postgresql"
                    else "portable_lexical_fallback"
                ),
                "vector_backend": "qdrant",
                "vector_status": vector_status,
                "fusion": "reciprocal_rank_fusion",
                "rrf_k": RRF_K,
                "reranker": "financial_source_hierarchy_v1",
            },
            "total": len(results),
            "results": results,
        }

    @staticmethod
    def _not_found(query: str, include_vector: bool) -> dict[str, Any]:
        return {
            "query": query,
            "status": "not_found",
            "retrieval": {"mode": "lexical_only", "vector_requested": include_vector},
            "total": 0,
            "results": [],
        }

    @staticmethod
    def _vector_key(row: dict[str, Any]) -> str:
        entity_type = row.get("entity_type")
        entity_id = row.get("entity_id")
        if entity_type and entity_id is not None:
            return f"{entity_type}:{entity_id}"
        return ""

    @staticmethod
    def _matches_filters(
        item: SearchCandidate,
        *,
        source_types: set[str] | None,
        statuses: set[str] | None,
        date_from: date | None,
        date_to: date | None,
    ) -> bool:
        if source_types and item.source_type not in source_types:
            return False
        if statuses and item.status not in statuses:
            return False
        item_date = item.as_of.date() if isinstance(item.as_of, datetime) else item.as_of
        if date_from and (item_date is None or item_date < date_from):
            return False
        if date_to and (item_date is None or item_date > date_to):
            return False
        return True

    @staticmethod
    def _fts(statement, column, query: str, db: Session):
        if db.bind and db.bind.dialect.name == "postgresql":
            tsquery = func.websearch_to_tsquery("simple", query)
            statement = statement.where(
                func.to_tsvector("simple", func.coalesce(column, "")).op("@@")(tsquery)
            )
        return statement

    @staticmethod
    def _allowed(entity_type: str, entity_types: set[str] | None) -> bool:
        return not entity_types or entity_type in entity_types

    def _candidates(
        self,
        db: Session,
        query: str,
        *,
        company: Company | None,
        entity_types: set[str] | None,
        collection_id: int | None,
    ) -> list[SearchCandidate]:
        result: list[SearchCandidate] = []
        company_id = company.id if company else None
        if collection_id is None:
            result.extend(self._company_corpus(db, query, company_id, entity_types))
        result.extend(
            self._knowledge_corpus(
                db,
                query,
                company_id,
                entity_types,
                collection_id=collection_id,
            )
        )
        return result

    def _hydrate_vector_candidates(
        self,
        db: Session,
        vector_rows: list[dict[str, Any]],
        *,
        company: Company | None,
        entity_types: set[str] | None,
        collection_id: int | None,
    ) -> list[SearchCandidate]:
        """Load canonical SQL records for Qdrant hits not returned by FTS."""
        ids_by_type: dict[str, set[int]] = {
            "document_chunk": set(),
            "knowledge_chunk": set(),
        }
        for row in vector_rows:
            entity_type = str(row.get("entity_type") or "")
            entity_id = row.get("entity_id")
            if (
                entity_type in ids_by_type
                and self._allowed(entity_type, entity_types)
                and isinstance(entity_id, int)
            ):
                ids_by_type[entity_type].add(entity_id)

        hydrated: list[SearchCandidate] = []
        document_ids = ids_by_type["document_chunk"]
        if document_ids and collection_id is None:
            statement = (
                select(DocumentChunk, Document, Company)
                .join(Document, DocumentChunk.document_id == Document.id)
                .outerjoin(Company, Document.company_id == Company.id)
                .where(DocumentChunk.id.in_(document_ids))
            )
            if company is not None:
                statement = statement.where(Document.company_id == company.id)
            for chunk, document, row_company in db.execute(statement).all():
                hydrated.append(
                    SearchCandidate(
                        key=f"document_chunk:{chunk.id}",
                        entity_type="document_chunk",
                        entity_id=chunk.id,
                        title=document.title,
                        text=chunk.text,
                        company_id=document.company_id,
                        ticker=row_company.ticker if row_company else None,
                        source_type=document.source_type,
                        source_url=document.source_url,
                        status="active",
                        as_of=document.published_at or document.created_at,
                        metadata={
                            "document_id": document.id,
                            "chunk_index": chunk.chunk_index,
                        },
                    )
                )

        knowledge_ids = ids_by_type["knowledge_chunk"]
        if knowledge_ids:
            statement = (
                select(KnowledgeChunk, KnowledgeDocument, KnowledgeCollection)
                .join(
                    KnowledgeDocument,
                    KnowledgeChunk.knowledge_document_id == KnowledgeDocument.id,
                )
                .outerjoin(
                    KnowledgeCollection,
                    KnowledgeDocument.collection_id == KnowledgeCollection.id,
                )
                .where(KnowledgeChunk.id.in_(knowledge_ids))
            )
            if collection_id is not None:
                statement = statement.where(KnowledgeDocument.collection_id == collection_id)
            for chunk, document, collection in db.execute(statement).all():
                hydrated.append(
                    SearchCandidate(
                        key=f"knowledge_chunk:{chunk.id}",
                        entity_type="knowledge_chunk",
                        entity_id=chunk.id,
                        title=document.title,
                        text=chunk.content,
                        source_type=document.document_type,
                        source_url=document.source_url,
                        collection_id=document.collection_id,
                        collection=collection.name if collection else None,
                        status=document.status,
                        as_of=document.publication_date or document.created_at,
                        metadata={
                            "knowledge_document_id": document.id,
                            "page_number": chunk.page_number,
                            "source_locator": chunk.source_locator,
                        },
                    )
                )
        return hydrated

    def _company_corpus(
        self,
        db: Session,
        query: str,
        company_id: int | None,
        entity_types: set[str] | None,
    ) -> Iterable[SearchCandidate]:
        result: list[SearchCandidate] = []
        if self._allowed("document_chunk", entity_types):
            statement = (
                select(DocumentChunk, Document, Company)
                .join(Document, DocumentChunk.document_id == Document.id)
                .outerjoin(Company, Document.company_id == Company.id)
            )
            if company_id is not None:
                statement = statement.where(Document.company_id == company_id)
            statement = self._fts(statement, DocumentChunk.text, query, db).limit(300)
            for chunk, document, company in _rows(db, statement):
                result.append(
                    SearchCandidate(
                        key=f"document_chunk:{chunk.id}",
                        entity_type="document_chunk",
                        entity_id=chunk.id,
                        title=document.title,
                        text=chunk.text,
                        company_id=document.company_id,
                        ticker=company.ticker if company else None,
                        source_type=document.source_type,
                        source_url=document.source_url,
                        status="active",
                        as_of=document.published_at or document.created_at,
                        metadata={
                            "document_id": document.id,
                            "chunk_index": chunk.chunk_index,
                        },
                    )
                )
        result.extend(self._narrative_candidates(db, query, company_id, entity_types))
        result.extend(self._metric_candidates(db, query, company_id, entity_types))
        if self._allowed("decision", entity_types):
            statement = select(DecisionJournalEntry)
            if company_id is not None:
                statement = statement.where(DecisionJournalEntry.company_id == company_id)
            statement = self._fts(statement, DecisionJournalEntry.rationale, query, db).limit(300)
            for row in db.scalars(statement).all():
                result.append(
                    SearchCandidate(
                        key=f"decision:{row.id}",
                        entity_type="decision",
                        entity_id=row.id,
                        title=f"Decisión: {row.decision}",
                        text=f"{row.rationale} {' '.join(row.what_must_be_true)}",
                        company_id=row.company_id,
                        source_type="user",
                        status=row.status,
                        as_of=row.decision_date,
                    )
                )
        return result

    def _narrative_candidates(
        self,
        db: Session,
        query: str,
        company_id: int | None,
        entity_types: set[str] | None,
    ) -> list[SearchCandidate]:
        result: list[SearchCandidate] = []
        specs = (
            ("claim", Claim, Claim.statement),
            ("thesis_section", ThesisSection, ThesisSection.body),
            ("decision_lesson", DecisionLesson, DecisionLesson.lesson),
        )
        for entity_type, model, text_column in specs:
            if not self._allowed(entity_type, entity_types):
                continue
            statement = select(model)
            if company_id is not None:
                statement = statement.where(model.company_id == company_id)
            statement = self._fts(statement, text_column, query, db).limit(300)
            for row in db.scalars(statement).all():
                if entity_type == "claim":
                    title, text = row.statement[:160], row.statement
                elif entity_type == "thesis_section":
                    title, text = row.title, row.body
                else:
                    title = f"Lección de decisión: {row.taxonomy}"
                    text = " ".join(
                        (
                            row.expectation,
                            row.outcome,
                            row.deviation,
                            row.cause,
                            row.error,
                            row.lesson,
                            row.future_application,
                        )
                    )
                result.append(
                    SearchCandidate(
                        key=f"{entity_type}:{row.id}",
                        entity_type=entity_type,
                        entity_id=row.id,
                        title=title,
                        text=text,
                        company_id=row.company_id,
                        source_type=("user" if entity_type == "decision_lesson" else "research"),
                        status=row.status,
                        as_of=row.updated_at,
                    )
                )
        return result

    def _metric_candidates(
        self,
        db: Session,
        query: str,
        company_id: int | None,
        entity_types: set[str] | None,
    ) -> list[SearchCandidate]:
        result: list[SearchCandidate] = []
        for entity_type, model in (
            ("financial_fact", FinancialFact),
            ("calculated_metric", CalculatedMetric),
        ):
            if not self._allowed(entity_type, entity_types):
                continue
            statement = select(model, Company).join(Company, model.company_id == Company.id)
            if company_id is not None:
                statement = statement.where(model.company_id == company_id)
            statement = self._fts(statement, model.metric, query, db).limit(500)
            for row, row_company in _rows(db, statement):
                result.append(
                    SearchCandidate(
                        key=f"{entity_type}:{row.id}",
                        entity_type=entity_type,
                        entity_id=row.id,
                        title=f"{row_company.ticker} {row.metric} {row.period}",
                        text=f"{row.metric} {row.value} {row.unit} {row.period}",
                        company_id=row.company_id,
                        ticker=row_company.ticker,
                        source_type=getattr(row, "source_type", "calculation"),
                        status=getattr(row, "status", "verified"),
                        as_of=row.updated_at,
                        metadata={
                            "period": row.period,
                            "value": str(row.value),
                            "unit": row.unit,
                        },
                    )
                )
        return result

    def _knowledge_corpus(
        self,
        db: Session,
        query: str,
        company_id: int | None,
        entity_types: set[str] | None,
        *,
        collection_id: int | None,
    ) -> Iterable[SearchCandidate]:
        result: list[SearchCandidate] = []
        if self._allowed("knowledge_chunk", entity_types):
            statement = (
                select(KnowledgeChunk, KnowledgeDocument, KnowledgeCollection)
                .join(
                    KnowledgeDocument,
                    KnowledgeChunk.knowledge_document_id == KnowledgeDocument.id,
                )
                .outerjoin(
                    KnowledgeCollection,
                    KnowledgeDocument.collection_id == KnowledgeCollection.id,
                )
            )
            if collection_id is not None:
                statement = statement.where(KnowledgeDocument.collection_id == collection_id)
            statement = self._fts(statement, KnowledgeChunk.content, query, db).limit(300)
            for chunk, document, collection in _rows(db, statement):
                result.append(
                    SearchCandidate(
                        key=f"knowledge_chunk:{chunk.id}",
                        entity_type="knowledge_chunk",
                        entity_id=chunk.id,
                        title=document.title,
                        text=chunk.content,
                        source_type=document.document_type,
                        source_url=document.source_url,
                        collection_id=document.collection_id,
                        collection=collection.name if collection else None,
                        status=document.status,
                        as_of=document.publication_date or document.created_at,
                        metadata={
                            "knowledge_document_id": document.id,
                            "page_number": chunk.page_number,
                            "source_locator": chunk.source_locator,
                        },
                    )
                )
        result.extend(self._principle_candidates(db, query, company_id, entity_types, collection_id))
        result.extend(self._case_candidates(db, query, company_id, entity_types, collection_id))
        return result

    def _principle_candidates(
        self,
        db: Session,
        query: str,
        company_id: int | None,
        entity_types: set[str] | None,
        collection_id: int | None,
    ) -> list[SearchCandidate]:
        if not self._allowed("investment_principle", entity_types):
            return []
        statement = (
            select(InvestmentPrinciple, KnowledgeDocument, KnowledgeCollection)
            .join(
                KnowledgeDocument,
                InvestmentPrinciple.knowledge_document_id == KnowledgeDocument.id,
            )
            .outerjoin(
                KnowledgeCollection,
                InvestmentPrinciple.collection_id == KnowledgeCollection.id,
            )
        )
        if collection_id is not None:
            statement = statement.where(InvestmentPrinciple.collection_id == collection_id)
        if company_id is not None:
            statement = statement.where(InvestmentPrinciple.applies_to_company_ids.contains([company_id]))
        statement = self._fts(statement, InvestmentPrinciple.principle, query, db).limit(300)
        result = []
        for row, document, collection in _rows(db, statement):
            result.append(
                SearchCandidate(
                    key=f"investment_principle:{row.id}",
                    entity_type="investment_principle",
                    entity_id=row.id,
                    title=f"Principle: {row.category}",
                    text=" ".join(
                        (
                            row.principle,
                            row.exact_fragment,
                            *row.application_conditions,
                            *row.exceptions,
                        )
                    ),
                    source_type=document.document_type,
                    source_url=document.source_url,
                    collection_id=row.collection_id,
                    collection=collection.name if collection else None,
                    status=row.status,
                    as_of=row.approved_at or row.created_at,
                    metadata={
                        "author": row.author,
                        "page_number": row.page_number,
                        "knowledge_document_id": row.knowledge_document_id,
                    },
                )
            )
        return result

    def _case_candidates(
        self,
        db: Session,
        query: str,
        company_id: int | None,
        entity_types: set[str] | None,
        collection_id: int | None,
    ) -> list[SearchCandidate]:
        if not self._allowed("investment_case", entity_types):
            return []
        statement = select(InvestmentCaseStudy, KnowledgeCollection).outerjoin(
            KnowledgeCollection,
            InvestmentCaseStudy.collection_id == KnowledgeCollection.id,
        )
        if collection_id is not None:
            statement = statement.where(InvestmentCaseStudy.collection_id == collection_id)
        if company_id is not None:
            statement = statement.where(InvestmentCaseStudy.company_id == company_id)
        statement = self._fts(statement, InvestmentCaseStudy.summary, query, db).limit(300)
        result = []
        for row, collection in _rows(db, statement):
            result.append(
                SearchCandidate(
                    key=f"investment_case:{row.id}",
                    entity_type="investment_case",
                    entity_id=row.id,
                    title=row.title,
                    text=" ".join((row.summary, row.outcome, *row.lessons)),
                    company_id=row.company_id,
                    source_type="historical_case",
                    collection_id=row.collection_id,
                    collection=collection.name if collection else None,
                    status=row.status,
                    as_of=row.updated_at,
                    metadata={"period": row.period, "sector": row.sector},
                )
            )
        return result
