"""Documento de fuente de ingestión: get-or-create por (empresa, tipo, título).

Siete servicios llevaban esta misma pieza copiada (class-based EPS, FMP, SEC,
ESEF, edgartools, evidencia de tesis e inputs WACC): localizar el Document que
acredita la fuente de unos hechos o crearlo con sus metadatos. Aquí vive una
sola vez; cada servicio conserva su envoltorio privado con su título, su URL
y sus metadatos (los tests llaman a esos envoltorios por nombre).
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.source_urls import linkable_source_url
from app.models import Company, Document


def get_or_create_source_document(
    db: Session,
    company: Company,
    *,
    title: str,
    source_type: str,
    source_url: str | None = None,
    metadata: dict | None = None,
    published_at: datetime | None = None,
    scrub_unlinkable_url: bool = False,
) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.company_id == company.id,
            Document.source_type == source_type,
            Document.title == title,
        )
    )
    if document is not None:
        if scrub_unlinkable_url and document.source_url and linkable_source_url(document.source_url) is None:
            # Una snapshot normalizada no tiene URL de filing verificada:
            # nunca se fabrica una clicable.
            document.source_url = None
        return document
    document = Document(
        company_id=company.id,
        title=title,
        source_type=source_type,
        source_url=source_url,
        metadata_=metadata,
        **({"published_at": published_at} if published_at is not None else {}),
    )
    db.add(document)
    db.flush()
    return document
