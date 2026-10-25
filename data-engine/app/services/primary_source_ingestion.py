"""Explicit official-source ingestion; a news article is never a primary record."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk, NewsEvent, PrimarySourceRecord
from app.services.document_ingestion_service import (
    MAX_DOCUMENT_BYTES,
    DocumentIngestionService,
    _extension,
)
from app.services.document_store import DocumentStore
from app.services.public_fetch import fetch_public_url

# Only explicit official registries. Adding a host requires source review, not
# automatic inference from a publisher article or a user-provided headline.
OFFICIAL_HOSTS = frozenset({"www.sec.gov", "sec.gov", "www.itu.int", "itu.int", "www.fcc.gov", "fcc.gov"})
CONTENT_TYPES = {"text/html", "application/xhtml+xml", "application/pdf", "text/plain"}


# Host oficial restringido a UN prefijo de ruta (no se abre el host entero).
# api-prod.fcc.gov/icfs-attachment/ sirve los adjuntos del registro ICFS de la FCC
# (p. ej. solicitudes de modificacion de satelites); el resto del host no cuenta.
OFFICIAL_PATH_HOSTS = {"api-prod.fcc.gov": ("/icfs-attachment/",)}


def _official(url: str) -> bool:
    try:
        parts = urlsplit(url)
        if not (parts.scheme == "https" and parts.username is None and parts.password is None
                and parts.port in (None, 443)):
            return False
        if parts.hostname in OFFICIAL_HOSTS:
            return True
        prefixes = OFFICIAL_PATH_HOSTS.get(parts.hostname or "")
        if not prefixes:
            return False
        lowered = parts.path.lower()
        if ".." in lowered or "%2e" in lowered or "%2f" in lowered or "\\" in parts.path or ";" in parts.path:
            return False
        return any(parts.path.startswith(prefix) and len(parts.path) > len(prefix) for prefix in prefixes)
    except ValueError:
        return False


def ingest_explicit_primary_source(
    db: Session, *, news_event_id: int, official_url: str | None,
    reference_kind: str,
) -> dict:
    """Persist fetched official bytes and cited chunks, never automatic research effects.

    The caller must supply a separately discovered official URL and its provenance.
    This routine does not scrape outbound links from news or claim that an article
    proves the contents of an official record.
    """
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant context required")
    event = db.scalar(select(NewsEvent).where(NewsEvent.id == news_event_id))
    if event is None or event.company_id is None:
        raise ValueError("Tenant-scoped news event with company required")
    if reference_kind not in {"regulator_connector", "official_registry", "verified_reference"}:
        raise ValueError("Untrusted primary-source reference kind")
    if not official_url:
        return {"primary_status": "not_found", "news_event_id": news_event_id}
    if not _official(official_url):
        raise ValueError("Primary source must be an explicit official HTTPS URL")
    # A caller-provided date is not proof that the official record published it.
    # This plumbing layer does not claim publication time until a source-specific
    # parser extracts and locates that field in the stored original.


    content, content_type, final_url = fetch_public_url(
        official_url, max_bytes=MAX_DOCUMENT_BYTES, timeout=20, allowed_url=_official,
    )
    if not _official(final_url):
        raise ValueError("Primary-source redirect left the official registry")
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime not in CONTENT_TYPES:
        raise ValueError("Unsupported primary-source content type")
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("Primary-source bytes absent or too large")
    if mime == "application/pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF signature")
    if mime != "application/pdf" and content.startswith(b"%PDF-"):
        raise ValueError("Content type does not match PDF bytes")
    checksum = hashlib.sha256(content).hexdigest()
    prior = db.scalar(select(PrimarySourceRecord).where(
        PrimarySourceRecord.tenant_id == tenant_id,
        PrimarySourceRecord.news_event_id == news_event_id,
        PrimarySourceRecord.final_url == final_url,
        PrimarySourceRecord.checksum == checksum,
    ))
    if prior:
        return {"primary_status": "parsed", "status": "duplicate", "document_id": prior.document_id,
                "record_id": prior.id, "checksum": checksum}

    path = PurePosixPath(urlsplit(final_url).path)
    ext = ".pdf" if mime == "application/pdf" else ".html" if mime in {"text/html", "application/xhtml+xml"} else ".txt"
    filename = path.name if path.suffix.lower() == ext else f"primary{ext}"
    ingestor = DocumentIngestionService()
    itu_record = None
    if urlsplit(final_url).path.startswith("/ITU-R/space/asreceived/Publication/DisplayPublication/"):
        from app.services.itu_record_parser import as_parsed_document, parse_itu_record

        itu_record = parse_itu_record(content, final_url)
        parsed = as_parsed_document(itu_record)
    else:
        parsed = ingestor._parse(content, filename, _extension(filename, mime), mime)
    chunks = ingestor._chunk_blocks(parsed.blocks, checksum, parsed.parser, filename, final_url)
    if not chunks or len(" ".join(chunk["text"] for chunk in chunks).strip()) < 20:
        raise ValueError("Primary-source parser produced too little text; no cited record created")
    fetched_at = datetime.now(UTC)
    from app.models import Company
    company = db.scalar(select(Company).where(Company.id == event.company_id))
    if company is None:
        raise ValueError("Event company no longer exists")
    existing = db.scalar(select(Document).where(
        Document.tenant_id == tenant_id, Document.company_id == company.id,
        Document.source_url == final_url, Document.checksum == checksum,
        Document.source_type == "primary_official",
    ))
    if existing is None:
        storage_uri = DocumentStore().put_bytes(company.ticker, "primary_official",
                                                f"{checksum[:12]}-{filename}", content,
                                                tenant_id=tenant_id, content_type=mime)
        document = Document(company_id=company.id, title=f"Official record: {filename}",
                            source_type="primary_official", source_url=final_url,
                            storage_uri=storage_uri, published_at=None,
                            checksum=checksum, metadata_={
                                "requested_url": official_url, "final_url": final_url,
                                "fetched_at": fetched_at.isoformat(), "date_source": "unknown",
                                "content_type": mime, "byte_count": len(content),
                                "parser": parsed.parser, "warnings": parsed.warnings,
                                "reference_kind": reference_kind,
                                "itu_record": ({"submission_id": itu_record.submission_id,
                                                "reference": itu_record.reference,
                                                "registry_date": (itu_record.registry_date.isoformat()
                                                                  if itu_record.registry_date else None),
                                                "receipt_date": (itu_record.receipt_date.isoformat()
                                                                 if itu_record.receipt_date else None),
                                                "frequency_url": itu_record.frequency_url,
                                                "frequencies_complete": False}
                                               if itu_record else None),
                            })
        db.add(document)
        db.flush()
        for index, chunk in enumerate(chunks):
            db.add(DocumentChunk(document_id=document.id, chunk_index=index,
                                 text=chunk["text"], token_count=len(chunk["text"].split()),
                                 metadata_=chunk["metadata"]))
    else:
        document = existing
    record = PrimarySourceRecord(news_event_id=event.id, document_id=document.id,
                                 requested_url=official_url, final_url=final_url,
                                 checksum=checksum, fetched_at=fetched_at,
                                 reference_kind=reference_kind)
    db.add(record)
    db.commit()
    return {"primary_status": "parsed", "status": "ingested", "record_id": record.id,
            "document_id": document.id, "checksum": checksum, "chunks": len(chunks),
            "source_url": final_url, "published_at": None}
