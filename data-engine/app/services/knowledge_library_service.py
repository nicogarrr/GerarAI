from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.llm import LLMProvider, LLMRequest, Message, ResponseFormat
from app.llm.chat_provider import create_background_llm_provider
from app.llm.json import parse_json_response
from app.models import (
    Company,
    InvestmentCaseStudy,
    InvestmentPrinciple,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
)
from app.services.budget import BudgetController
from app.services.document_ingestion_service import (
    MAX_DOCUMENT_BYTES,
    SUPPORTED_EXTENSIONS,
    DocumentIngestionService,
    _extension,
)
from app.services.document_store import DocumentStore
from app.services.evidence_contract import build_ingestion_evidence

DEFAULT_KNOWLEDGE_COLLECTIONS = (
    "Buffett & Munger",
    "Howard Marks",
    "Fundsmith",
    "Numantia",
    "Capital Allocation",
    "Cyclicals",
    "Compounders",
    "Pre-revenue",
    "Space Industry",
    "Personal Mistakes",
)

KNOWLEDGE_DOCUMENT_TYPES = {
    "fund_letter",
    "book",
    "article",
    "paper",
    "sector_report",
    "personal_note",
    "third_party_thesis",
    "own_thesis",
    "historical_case",
    "personal_postmortem",
}

from app.services.prompt_registry import get_prompt

PRINCIPLE_PROMPT_VERSION = get_prompt("investment_principles", allow_remote=False).version
PRINCIPLE_BATCH_MAX_CHARS = 24_000
PRINCIPLE_BATCH_MAX_CHUNKS = 12


# Forma de ticker aceptada en la biblioteca: letras/digitos y los separadores
# de clase o mercado habituales (BRK-B, SAN.MC, CGEO.L, ^GSPC, BTC-USD).
_KNOWLEDGE_TICKER_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,31}$")


def normalize_knowledge_ticker(value: str | None) -> str | None:
    """Ticker opcional de un documento: strip + upper; vacio -> ``None``.

    Lanza ``ValueError`` (mensaje fijo, apto para 400) si no tiene forma de
    ticker: con espacios, simbolos raros o mas de 32 caracteres.
    """
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        return None
    if not _KNOWLEDGE_TICKER_RE.fullmatch(normalized) or not re.search(r"[A-Z0-9]", normalized):
        raise ValueError("El ticker no es válido (ej.: AAPL, BRK-B, SAN.MC)")
    return normalized


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not normalized:
        raise ValueError("Collection name must contain letters or numbers")
    return normalized[:160]


def _compact(value: str) -> str:
    return " ".join(value.lower().split())


logger = logging.getLogger("gerarai.knowledge_library")


def extraction_error_message(exc: Exception) -> str:
    """Error de extracción legible para la UI: los fallos del modelo (timeout,
    caída, cuota) se explican en español natural en vez del `ProviderTransportError: ...`
    técnico en inglés. El detalle técnico queda en el log del actor."""
    from app.llm.errors import LLMError

    if isinstance(exc, LLMError):
        return (
            "El modelo de lenguaje no respondió o no está disponible ahora mismo. "
            "Vuelve a intentarlo en unos minutos."
        )
    # Se guarda en el documento y la UI lo enseña: sin redactar, un error de
    # httpx traía la URL del proveedor con ?apikey= tal cual.
    from app.core.errors import redact_secrets

    return redact_secrets(f"{type(exc).__name__}: {exc}")[:500]


class KnowledgeLibraryService:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider or create_background_llm_provider()
        self.parser = DocumentIngestionService()

    def ensure_default_collections(self, db: Session) -> list[KnowledgeCollection]:
        existing = {
            collection.slug: collection
            for collection in db.scalars(select(KnowledgeCollection)).all()
        }
        for name in DEFAULT_KNOWLEDGE_COLLECTIONS:
            slug = _slug(name)
            if slug not in existing:
                collection = KnowledgeCollection(
                    name=name,
                    slug=slug,
                    description=f"Canonical GerarAI collection for {name}.",
                    collection_type="system",
                    metadata_={"default": True},
                )
                db.add(collection)
                existing[slug] = collection
        db.commit()
        return list(
            db.scalars(select(KnowledgeCollection).order_by(KnowledgeCollection.name)).all()
        )

    def create_collection(
        self,
        db: Session,
        *,
        name: str,
        description: str = "",
        collection_type: str = "custom",
    ) -> KnowledgeCollection:
        slug = _slug(name)
        if db.scalar(select(KnowledgeCollection).where(KnowledgeCollection.slug == slug)):
            raise ValueError(f"Knowledge collection {name!r} already exists")
        collection = KnowledgeCollection(
            name=name.strip(),
            slug=slug,
            description=description.strip(),
            collection_type=collection_type.strip() or "custom",
            metadata_={},
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)
        return collection

    def ingest_bytes(
        self,
        db: Session,
        *,
        title: str,
        content: bytes,
        filename: str,
        document_type: str,
        collection_id: int | None = None,
        author: str | None = None,
        source_url: str | None = None,
        publication_date: date | None = None,
        language: str = "en",
        content_type: str | None = None,
        ticker: str | None = None,
    ) -> dict[str, Any]:
        normalized_ticker = normalize_knowledge_ticker(ticker)
        if not content:
            raise ValueError("Knowledge document is empty")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise ValueError("Knowledge document exceeds 15MB local ingestion limit")
        if document_type not in KNOWLEDGE_DOCUMENT_TYPES:
            raise ValueError(f"Unsupported knowledge document type: {document_type}")
        collection = db.get(KnowledgeCollection, collection_id) if collection_id else None
        if collection_id and collection is None:
            raise ValueError("Knowledge collection not found")

        checksum = hashlib.sha256(content).hexdigest()
        duplicate = db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.checksum == checksum)
        )
        if duplicate:
            return {
                "status": "duplicate",
                "knowledge_document_id": duplicate.id,
                "checksum": checksum,
                "chunks": 0,
            }

        extension = _extension(filename, content_type)
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported document extension: {extension}")
        parsed = self.parser._parse(content, filename, extension, content_type)
        if sum(len(block.text.strip()) for block in parsed.blocks) < 20:
            raise ValueError("Knowledge document parser produced too little text")

        storage_uri = DocumentStore().put_bytes(
            "KNOWLEDGE",
            document_type,
            f"{checksum[:12]}-{Path(filename).name}",
            content,
            tenant_id=db.info.get("tenant_id"),
            content_type=content_type or "application/octet-stream",
        )
        document = KnowledgeDocument(
            collection_id=collection.id if collection else None,
            title=title.strip(),
            author=author.strip() if author else None,
            document_type=document_type,
            source_url=source_url,
            storage_uri=storage_uri,
            publication_date=publication_date,
            language=language.strip().lower()[:20] or "en",
            status="ready",
            checksum=checksum,
            ticker=normalized_ticker,
            metadata_={
                "filename": filename,
                "content_type": content_type,
                "parser": parsed.parser,
                "warnings": parsed.warnings,
                "raw_size_bytes": len(content),
            },
        )
        db.add(document)
        db.flush()

        chunks = self.parser._chunk_blocks(
            parsed.blocks,
            checksum,
            parsed.parser,
            filename,
            source_url,
        )
        evidence = build_ingestion_evidence(
            tenant_id=db.info.get("tenant_id"), document_id=f"knowledge:{document.id}",
            checksum=checksum, source_type=document_type, chunks=chunks, url=source_url,
            author=author, published_on=publication_date, language=document.language,
        )
        document.metadata_ = {**document.metadata_, "evidence_contract": evidence}
        for index, payload in enumerate(chunks):
            payload["metadata"] = {
                **payload["metadata"],
                "evidence_source_id": evidence.get("source_id"),
                "evidence_chunk_id": evidence.get("chunks", [{}] * len(chunks))[index].get("chunk_id"),
            }
            block_metadata = payload["metadata"].get("block_metadata") or []
            page = next(
                (
                    item.get("page")
                    for item in block_metadata
                    if isinstance(item, dict) and isinstance(item.get("page"), int)
                ),
                None,
            )
            db.add(
                KnowledgeChunk(
                    knowledge_document_id=document.id,
                    chunk_index=index,
                    content=payload["text"],
                    page_number=page,
                    token_count=len(payload["text"].split()),
                    source_locator={
                        "knowledge_document_id": document.id,
                        "chunk_index": index,
                        "page": page,
                        "source_url": source_url,
                    },
                    metadata_=payload["metadata"],
                )
            )
        db.commit()
        db.refresh(document)
        vector_index = {"status": "disabled", "chunks_indexed": 0}
        if os.getenv("CAVAAI_ENABLE_VECTOR_INGEST") == "1":
            from app.services.rag import RAGIndex

            vector_index = {
                "status": "attempted",
                **RAGIndex().ingest_knowledge_document(db, document),
            }
        return {
            "status": "ingested",
            "knowledge_document_id": document.id,
            "collection_id": document.collection_id,
            "checksum": checksum,
            "chunks": len(chunks),
            "parser": parsed.parser,
            "storage_uri": storage_uri,
            "warnings": parsed.warnings,
            "vector_index": vector_index,
        }

    async def propose_principles(
        self,
        db: Session,
        document: KnowledgeDocument,
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[InvestmentPrinciple]:
        result = await self.extract_principle_batches(db, document, progress=progress)
        return result["principles"]

    async def extract_principle_batches(
        self,
        db: Session,
        document: KnowledgeDocument,
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        chunks = list(
            db.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.knowledge_document_id == document.id)
                .order_by(KnowledgeChunk.chunk_index)
            ).all()
        )
        if not chunks:
            raise ValueError("Knowledge document has no chunks")
        batches = self._principle_batches(chunks)
        companies = {
            company.ticker.upper(): company.id for company in db.scalars(select(Company)).all()
        }
        created: list[InvestmentPrinciple] = []
        exact_duplicates = 0
        semantic_duplicates = 0
        # El bucle de lotes es el unico lugar del motor que puede disparar
        # muchas llamadas seguidas (un documento de 1 MB son ~40 lotes), y era
        # el unico sin gate de presupuesto: 40 llamadas sin pasar por
        # budget.can_spend ni por budget.record. Se comprueba por lote con un
        # tope por llamada derivado del tamano real del prompt.
        budget = BudgetController()
        budget_stopped = False
        batches_processed = 0
        for batch_index, batch in enumerate(batches, start=1):
            source = "\n\n".join(
                f"[chunk:{chunk.id} page:{chunk.page_number or 'unknown'} "
                f"section:{chunk.section_title or 'unknown'}]\n{chunk.content}"
                for chunk in batch
            )
            # Estimacion con el tamano real del prompt (~4 caracteres por token)
            # y el max_tokens de la llamada, en vez del 0.02 plano que usan otros
            # sitios: aqui el input es de 24.000 caracteres por lote.
            planned_cost_eur = budget.estimate_cost_eur(
                getattr(self.provider, "name", "") or "",
                input_tokens=len(source) // 4,
                output_tokens=3000,
            )
            if not budget.can_spend(db, planned_cost_eur):
                logger.info(
                    "principle extraction stopped at batch %s/%s: budget",
                    batch_index,
                    len(batches),
                )
                budget_stopped = True
                break
            # Nada pendiente de escritura en este punto: el commit cierra la
            # transaccion de lectura (chunks/companies/can_spend) para que el
            # await del LLM (segundos o minutos) no deje la sesion "idle in
            # transaction" reteniendo locks. chunks, companies y document ya
            # estan materializados y expire_on_commit=False los mantiene.
            db.commit()
            response = await self.provider.complete(
                LLMRequest(
                    messages=[
                        Message(
                            "system",
                            get_prompt("investment_principles").text,
                        ),
                        Message("user", source),
                    ],
                    task="main_financial_analysis",
                    temperature=0,
                    max_tokens=3000,
                    response_format=ResponseFormat.json_schema(
                        self._principle_schema(),
                        name="investment_principles",
                        strict=True,
                    ),
                    metadata={
                        "prompt_version": PRINCIPLE_PROMPT_VERSION,
                        "batch_index": str(batch_index),
                        "batch_count": str(len(batches)),
                    },
                )
            )
            payload = parse_json_response(response.text)
            # Contabilidad del gasto: sin este record, ninguna de las llamadas
            # de este bucle aparecia en budget_usage, asi que el gasto real no
            # se compedia contra el tope diario.
            budget.record(
                db,
                response.model,
                "investment_principles",
                budget.estimate_cost_eur(
                    response.model,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                ),
                response.usage.total_tokens,
                commit=False,
            )
            if not isinstance(payload, dict) or not isinstance(
                payload.get("principles"), list
            ):
                raise ValueError("Invalid investment principle extraction response")
            chunks_by_id = {chunk.id: chunk for chunk in batch}
            for item in payload["principles"]:
                outcome = self._create_principle_candidate(
                    db,
                    document=document,
                    chunks_by_id=chunks_by_id,
                    companies=companies,
                    item=item,
                    response=response,
                    batch_index=batch_index,
                    batch_count=len(batches),
                )
                if outcome is None:
                    continue
                if isinstance(outcome, InvestmentPrinciple):
                    created.append(outcome)
                    if outcome.semantic_duplicate_of_id is not None:
                        semantic_duplicates += 1
                else:
                    exact_duplicates += 1
            db.commit()
            batches_processed += 1
            if progress:
                progress(batch_index, len(batches))

        contradictions = self._contradictions(created)
        return {
            "principles": created,
            "batch_count": len(batches),
            # Corte por presupuesto: el documento NO esta completo. El llamador
            # lo marca "partial" en vez de "completed".
            "budget_stopped": budget_stopped,
            "batches_processed": batches_processed,
            "exact_duplicates": exact_duplicates,
            "semantic_duplicates": semantic_duplicates,
            "contradictions": contradictions,
        }

    def decide_principle(
        self,
        db: Session,
        principle: InvestmentPrinciple,
        *,
        action: str,
        actor: str,
    ) -> InvestmentPrinciple:
        if principle.status != "proposed":
            raise ValueError("Only proposed principles can be approved or rejected")
        if action not in {"approve", "reject"}:
            raise ValueError("Principle action must be approve or reject")
        principle.status = "approved" if action == "approve" else "rejected"
        principle.approved_by = actor
        principle.approved_at = datetime.now(UTC)
        db.commit()
        db.refresh(principle)
        return principle

    def merge_principle(
        self,
        db: Session,
        principle: InvestmentPrinciple,
        *,
        canonical: InvestmentPrinciple,
        actor: str,
    ) -> InvestmentPrinciple:
        if principle.status != "proposed":
            raise ValueError("Only proposed principles can be merged")
        if canonical.id == principle.id or canonical.status not in {"proposed", "approved"}:
            raise ValueError("Merge target must be another active principle")
        principle.status = "merged"
        principle.semantic_duplicate_of_id = canonical.id
        principle.canonical_principle_id = canonical.canonical_principle_id or canonical.id
        principle.approved_by = actor
        principle.approved_at = datetime.now(UTC)
        db.commit()
        db.refresh(principle)
        return principle

    def revise_principle(
        self,
        db: Session,
        principle: InvestmentPrinciple,
        *,
        changes: dict[str, Any],
        actor: str,
    ) -> InvestmentPrinciple:
        if principle.status in {"rejected", "merged", "superseded"}:
            raise ValueError("Only active principles can be revised")
        values = {
            "principle": str(changes.get("principle", principle.principle)).strip(),
            "category": str(changes.get("category", principle.category)).strip()[:120],
            "application_conditions": self._strings(
                changes.get("application_conditions", principle.application_conditions)
            ),
            "exceptions": self._strings(changes.get("exceptions", principle.exceptions)),
        }
        if not values["principle"]:
            raise ValueError("Principle text is required")
        canonical_id = principle.canonical_principle_id or principle.id
        version = (
            db.scalar(
                select(InvestmentPrinciple.version)
                .where(
                    (InvestmentPrinciple.id == canonical_id)
                    | (InvestmentPrinciple.canonical_principle_id == canonical_id),
                    *tenant_filters(db, InvestmentPrinciple),
                )
                .order_by(desc(InvestmentPrinciple.version))
                .limit(1)
            )
            or principle.version
        ) + 1
        revised = InvestmentPrinciple(
            knowledge_document_id=principle.knowledge_document_id,
            knowledge_chunk_id=principle.knowledge_chunk_id,
            collection_id=principle.collection_id,
            **values,
            principle_fingerprint=self.principle_fingerprint(**values),
            canonical_principle_id=canonical_id,
            version=version,
            applies_to_company_ids=changes.get(
                "applies_to_company_ids", principle.applies_to_company_ids
            ),
            exact_fragment=str(changes.get("exact_fragment", principle.exact_fragment)),
            page_number=changes.get("page_number", principle.page_number),
            author=changes.get("author", principle.author),
            confidence=Decimal(str(changes.get("confidence", principle.confidence))),
            status="proposed",
            metadata_={
                **(principle.metadata_ or {}),
                "revised_from_id": principle.id,
                "revised_by": actor,
            },
        )
        db.add(revised)
        db.flush()
        principle.superseded_by_id = revised.id
        principle.status = "superseded"
        db.commit()
        db.refresh(revised)
        return revised

    @staticmethod
    def principle_fingerprint(
        *,
        principle: str,
        category: str,
        application_conditions: list[str],
        exceptions: list[str],
    ) -> str:
        canonical = json.dumps(
            {
                "principle": _compact(principle),
                "category": _compact(category),
                "conditions": sorted(_compact(item) for item in application_conditions),
                "exceptions": sorted(_compact(item) for item in exceptions),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _create_principle_candidate(
        self,
        db: Session,
        *,
        document: KnowledgeDocument,
        chunks_by_id: dict[int, KnowledgeChunk],
        companies: dict[str, int],
        item: Any,
        response: Any,
        batch_index: int,
        batch_count: int,
    ) -> InvestmentPrinciple | str | None:
        if not isinstance(item, dict):
            return None
        chunk_id = self._integer(item.get("chunk_id"))
        chunk = chunks_by_id.get(chunk_id) if chunk_id is not None else None
        fragment = str(item.get("exact_fragment") or "").strip()
        text = str(item.get("principle") or "").strip()
        if (
            chunk is None
            or not text
            or not fragment
            or _compact(fragment) not in _compact(chunk.content)
        ):
            return None
        category = str(item.get("category") or "general")[:120]
        conditions = self._strings(item.get("application_conditions"))
        exceptions = self._strings(item.get("exceptions"))
        fingerprint = self.principle_fingerprint(
            principle=text,
            category=category,
            application_conditions=conditions,
            exceptions=exceptions,
        )
        existing = db.scalar(
            select(InvestmentPrinciple)
            .where(
                InvestmentPrinciple.principle_fingerprint == fingerprint,
                InvestmentPrinciple.status.in_(["proposed", "approved"]),
            )
            .order_by(InvestmentPrinciple.id)
        )
        if existing:
            return "exact_duplicate"
        semantic = self._semantic_duplicate(db, text)
        confidence = max(0.0, min(1.0, float(item.get("confidence") or 0)))
        principle = InvestmentPrinciple(
            knowledge_document_id=document.id,
            knowledge_chunk_id=chunk.id,
            collection_id=document.collection_id,
            principle=text,
            principle_fingerprint=fingerprint,
            semantic_duplicate_of_id=semantic.id if semantic else None,
            canonical_principle_id=(
                semantic.canonical_principle_id or semantic.id if semantic else None
            ),
            version=1,
            category=category,
            application_conditions=conditions,
            exceptions=exceptions,
            applies_to_company_ids=[
                companies[ticker.upper()]
                for ticker in self._strings(item.get("company_tickers"))
                if ticker.upper() in companies
            ],
            exact_fragment=fragment,
            page_number=chunk.page_number,
            author=document.author,
            confidence=Decimal(str(confidence)),
            status="proposed",
            metadata_={
                "model": response.model,
                "provider": response.provider,
                "request_id": response.request_id,
                "prompt_version": PRINCIPLE_PROMPT_VERSION,
                "batch_index": batch_index,
                "batch_count": batch_count,
                "requires_duplicate_review": semantic is not None,
            },
        )
        db.add(principle)
        db.flush()
        return principle

    @staticmethod
    def _principle_batches(chunks: list[KnowledgeChunk]) -> list[list[KnowledgeChunk]]:
        batches: list[list[KnowledgeChunk]] = []
        current: list[KnowledgeChunk] = []
        current_chars = 0
        current_section: str | None = None
        for chunk in chunks:
            section = _compact(chunk.section_title or "") or None
            section_break = bool(
                current and section and current_section and section != current_section
            )
            size_break = bool(
                current
                and (
                    current_chars + len(chunk.content) > PRINCIPLE_BATCH_MAX_CHARS
                    or len(current) >= PRINCIPLE_BATCH_MAX_CHUNKS
                )
            )
            if section_break or size_break:
                batches.append(current)
                current = []
                current_chars = 0
            current.append(chunk)
            current_chars += len(chunk.content)
            current_section = section or current_section
        if current:
            batches.append(current)
        return batches

    def _semantic_duplicate(
        self, db: Session, text: str
    ) -> InvestmentPrinciple | None:
        candidates = db.scalars(
            select(InvestmentPrinciple).where(
                InvestmentPrinciple.status.in_(["proposed", "approved"])
            )
        ).all()
        tokens = self._semantic_tokens(text)
        best: tuple[float, InvestmentPrinciple] | None = None
        for candidate in candidates:
            candidate_tokens = self._semantic_tokens(candidate.principle)
            union = tokens | candidate_tokens
            score = len(tokens & candidate_tokens) / len(union) if union else 0
            if score >= 0.82 and (best is None or score > best[0]):
                best = (score, candidate)
        return best[1] if best else None

    @staticmethod
    def _semantic_tokens(text: str) -> set[str]:
        stop = {"a", "an", "and", "for", "in", "of", "the", "to", "with"}
        return {
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if token not in stop
        }

    def _contradictions(self, principles: list[InvestmentPrinciple]) -> list[dict[str, int]]:
        contradictions: list[dict[str, int]] = []
        negations = {"avoid", "never", "not", "reject", "without"}
        for index, left in enumerate(principles):
            left_tokens = self._semantic_tokens(left.principle)
            for right in principles[index + 1 :]:
                right_tokens = self._semantic_tokens(right.principle)
                overlap = left_tokens | right_tokens
                similarity = (
                    len(left_tokens & right_tokens) / len(overlap) if overlap else 0
                )
                left_negative = bool(left_tokens & negations)
                right_negative = bool(right_tokens & negations)
                if similarity >= 0.55 and left_negative != right_negative:
                    contradictions.append({"left_id": left.id, "right_id": right.id})
        return contradictions

    @staticmethod
    def document_dict(document: KnowledgeDocument) -> dict:
        return {
            "id": document.id,
            "collection_id": document.collection_id,
            "title": document.title,
            "author": document.author,
            "document_type": document.document_type,
            "source_url": document.source_url,
            "publication_date": document.publication_date,
            "language": document.language,
            "status": document.status,
            "checksum": document.checksum,
            "ticker": document.ticker,
            "metadata": document.metadata_,
            "created_at": document.created_at,
        }

    @staticmethod
    def list_documents(
        db: Session, *, collection_id: int | None = None, limit: int = 200,
        offset: int = 0, document_type: str | None = None, status: str | None = None,
        ticker: str | None = None,
    ) -> list[dict]:
        statement = (
            select(KnowledgeDocument)
            .order_by(desc(KnowledgeDocument.created_at), desc(KnowledgeDocument.id))
            .limit(limit).offset(offset)
        )
        if collection_id is not None:
            statement = statement.where(KnowledgeDocument.collection_id == collection_id)
        if document_type is not None:
            statement = statement.where(KnowledgeDocument.document_type == document_type)
        if status is not None:
            statement = statement.where(KnowledgeDocument.status == status)
        if ticker is not None and ticker.strip():
            # Se guarda normalizado (upper): el filtro normaliza igual, asi
            # ``?ticker=san.mc`` encuentra ``SAN.MC``.
            statement = statement.where(KnowledgeDocument.ticker == ticker.strip().upper())
        return [
            KnowledgeLibraryService.document_dict(document)
            for document in db.scalars(statement).all()
        ]

    @staticmethod
    def search_documents(
        db: Session, query: str, *, limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        """Busca documentos del tenant por título, autor o ticker.

        Cada palabra de ``query`` debe aparecer (sin distinguir mayúsculas)
        en alguno de esos campos. ILIKE basta a esta escala (cientos de
        documentos por tenant), sin índice nuevo ni migración. ``%`` y ``_``
        se buscan literalmente. El recuento lleva el filtro de tenant
        explícito: los agregados no pasan por el filtro ORM.
        """
        terms = [term for term in query.split() if term][:8]
        if not terms:
            return {"items": [], "total": 0, "query": ""}
        conditions = []
        for term in terms:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            conditions.append(
                KnowledgeDocument.title.ilike(pattern, escape="\\")
                | KnowledgeDocument.author.ilike(pattern, escape="\\")
                | KnowledgeDocument.ticker.ilike(pattern, escape="\\")
            )
        where = [*tenant_filters(db, KnowledgeDocument), *conditions]
        total = db.scalar(select(func.count()).select_from(KnowledgeDocument).where(*where)) or 0
        statement = (
            select(KnowledgeDocument).where(*where)
            .order_by(desc(KnowledgeDocument.created_at), desc(KnowledgeDocument.id))
            .limit(limit).offset(offset)
        )
        return {
            "items": [
                KnowledgeLibraryService.document_dict(document)
                for document in db.scalars(statement).all()
            ],
            "total": total,
            "query": " ".join(terms),
        }

    @staticmethod
    def set_document_ticker(
        db: Session, document: KnowledgeDocument, ticker: str | None
    ) -> dict:
        """Asigna, cambia o quita (``None``/vacio) el ticker de un documento."""
        document.ticker = normalize_knowledge_ticker(ticker)
        db.commit()
        db.refresh(document)
        return KnowledgeLibraryService.document_dict(document)

    @staticmethod
    def delete_document(db: Session, document: KnowledgeDocument) -> dict[str, int]:
        """Borra un documento de conocimiento y lo derivado de el.

        Cascada: principios extraidos (FK obligatoria), fragmentos y, en
        mejor esfuerzo, sus puntos vectoriales (Qdrant es un indice
        desechable: ``rebuild_tenant`` lo recrea desde PostgreSQL, asi que
        un fallo alli no bloquea el borrado). Los casos de estudio
        conservan su contenido y solo pierden el enlace (FK nullable).
        Los filtros de tenant de la sesion (eventos de database.py) se
        aplican a cada sentencia. Devuelve contadores para logs y tests.
        """
        principles = db.execute(
            delete(InvestmentPrinciple).where(
                InvestmentPrinciple.knowledge_document_id == document.id
            )
        ).rowcount
        db.execute(
            update(InvestmentCaseStudy)
            .where(InvestmentCaseStudy.knowledge_document_id == document.id)
            .values(knowledge_document_id=None)
        )
        chunks = db.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.knowledge_document_id == document.id
            )
        ).rowcount
        KnowledgeLibraryService._delete_vector_points(db, document)
        # El original en MinIO/Garage forma parte del documento: borrar solo
        # las filas dejaba el fichero accesible para siempre. Si el almacen
        # falla, no se confirma el borrado y el usuario puede reintentarlo.
        storage_uri = document.storage_uri
        DocumentStore().delete(storage_uri)
        db.delete(document)
        db.commit()
        logger.info(
            "knowledge document %s deleted (%s chunks, %s principles, original=%s)",
            document.id, chunks, principles, bool(storage_uri),
        )
        return {"chunks_deleted": int(chunks), "principles_deleted": int(principles)}

    @staticmethod
    def delete_collection(db: Session, collection: KnowledgeCollection) -> dict[str, int]:
        """Borra una coleccion VACIA de conocimiento.

        La ruta rechaza con 409 las colecciones que aun tienen documentos,
        asi que aqui solo cae la fila; los filtros de tenant de la sesion
        se aplican a la sentencia. Devuelve contadores para logs y tests.
        """
        db.delete(collection)
        db.commit()
        return {"collections": 1}

    @staticmethod
    def _delete_vector_points(db: Session, document: KnowledgeDocument) -> None:
        """Mejor esfuerzo: quita los puntos Qdrant del documento.

        Se intenta siempre, aunque la ingesta vectorial este apagada en este
        proceso: el flag solo controla si se *escriben* vectores, no si se
        limpian los que otro worker pudo escribir. Si Qdrant no responde se
        registra el fallo y no se bloquea el borrado de la fila, sus
        fragmentos y el original; el indice es reconstruible.
        """
        try:
            tenant_id = db.info.get("tenant_id")
            if tenant_id is None:
                return
            from app.services.rag import RAGIndex

            RAGIndex().delete_knowledge_document_points(tenant_id, document.id)
        except Exception:  # noqa: BLE001 - mejor esfuerzo, ver docstring
            logger.warning(
                "knowledge vector delete failed for document %s",
                document.id, exc_info=True,
            )

    @staticmethod
    def get_document(db: Session, document_id: int) -> dict | None:
        """Un documento por id, con el numero total de fragmentos (``chunk_count``)."""
        document = db.get(KnowledgeDocument, document_id)
        if document is None:
            return None
        count = db.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(
                KnowledgeChunk.knowledge_document_id == document_id,
                *tenant_filters(db, KnowledgeChunk),
            )
        )
        return {**KnowledgeLibraryService.document_dict(document), "chunk_count": int(count or 0)}

    @staticmethod
    def _strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _integer(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _principle_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "principles": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "principle": {"type": "string"},
                            "category": {"type": "string"},
                            "application_conditions": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "exceptions": {"type": "array", "items": {"type": "string"}},
                            "company_tickers": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "exact_fragment": {"type": "string"},
                            "chunk_id": {"type": "integer"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": [
                            "principle",
                            "category",
                            "application_conditions",
                            "exceptions",
                            "company_tickers",
                            "exact_fragment",
                            "chunk_id",
                            "confidence",
                        ],
                    },
                }
            },
            "required": ["principles"],
        }
