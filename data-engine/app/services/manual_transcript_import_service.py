import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Document, DocumentChunk, Transcript
from app.services.company_resolver import resolve_company

logger = logging.getLogger(__name__)


class ManualTranscriptImportService:
    """Persist transcript text exported from any external IR source."""

    def import_text(
        self,
        db: Session,
        ticker: str,
        title: str,
        text: str,
        source_url: str | None = None,
        period: str = "unknown",
    ) -> dict:
        company = resolve_company(db, ticker)
        if not company:
            raise ValueError(f"Unknown ticker: {ticker}")

        # Identidad estable por contenido: reimportar la misma transcripción
        # (mismo texto para la misma empresa del tenant) no duplica el
        # documento, sus chunks ni su índice RAG; devuelve el registro previo.
        checksum = hashlib.sha256(text.encode()).hexdigest()
        prior = db.scalar(
            select(Document).where(
                Document.checksum == checksum,
                Document.company_id == company.id,
                Document.source_type == "manual_transcript",
                *tenant_filters(db, Document),
            ).limit(1)
        )
        if prior is not None:
            transcript_id = db.scalar(
                select(Transcript.id).where(Transcript.source_id == prior.id).limit(1)
            )
            return {
                "document_id": prior.id,
                "transcript_id": transcript_id,
                "ticker": company.ticker,
                "chunks": 0,
                "source_type": "manual_transcript",
                "already_imported": True,
            }

        document = Document(
            company_id=company.id,
            title=title,
            source_type="manual_transcript",
            source_url=source_url,
            checksum=checksum,
            published_at=datetime.now(UTC),
            metadata_={
                "source_app": "external_ir_source",
                "ingestion_mode": "manual_export_or_copy_paste",
            },
        )
        db.add(document)
        db.flush()

        chunk_size = 3500
        chunks = [
            text[index : index + chunk_size]
            for index in range(0, len(text), chunk_size)
        ]
        for index, chunk in enumerate(chunks):
            db.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=index,
                    text=chunk,
                    token_count=max(1, len(chunk) // 4),
                    metadata_={
                        "ticker": company.ticker,
                        "source_type": "manual_transcript",
                    },
                )
            )

        transcript = Transcript(
            company_id=company.id,
            title=title,
            period=period,
            source_id=document.id,
            transcript_text=text,
        )
        db.add(transcript)
        db.commit()
        db.refresh(document)

        try:
            from app.services.rag import RAGIndex

            RAGIndex().ingest_document(db, document)
        except Exception:
            logger.warning("transcript_rag_ingest_failed: la transcripcion se guardo pero no quedo indexada en RAG", exc_info=True)

        return {
            "document_id": document.id,
            "transcript_id": transcript.id,
            "ticker": company.ticker,
            "chunks": len(chunks),
            "source_type": "manual_transcript",
        }
