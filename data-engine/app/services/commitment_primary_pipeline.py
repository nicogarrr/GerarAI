"""Tuberia de evidencia primaria: activo EXACTO registrado -> bytes -> texto -> cita.

- Solo descarga una URL que sea EXACTAMENTE un activo registrado (transcript_source_registry);
  host/prefijo no bastan. Sin redirects permitidos (igualdad exacta tambien en redirects).
- Registra hash de los BYTES descargados, hash del texto y version del extractor.
- Las paginas se separan con '\\f' para que el motor recupere el numero de pagina.
- No escribe en BD ni persiste el texto. La cita final la produce el adaptador estrecho
  (followup_primary_evidence_adapter); aqui no hay veredictos ni heuristicas nuevas.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO

from app.services.followup_primary_evidence_adapter import (
    PrimaryAsset,
    PrimaryEvidenceResult,
    ReportedObservation,
    asset_from_registry,
    extract_primary_evidence,
)
from app.services.public_fetch import fetch_public_url
from app.services.transcript_source_registry import get_entry, is_official_transcript_url

MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 80
MAX_TEXT_CHARS = 1_500_000
TIMEOUT_SECONDS = 25.0


class PrimarySourceError(ValueError):
    pass


@dataclass(frozen=True)
class RegisteredDocument:
    asset: PrimaryAsset
    url: str
    bytes_sha256: str
    byte_size: int
    text: str  # paginas separadas por '\f'
    text_sha256: str
    extractor: str
    fetched_on: date


@dataclass(frozen=True)
class PipelineResult:
    result: PrimaryEvidenceResult
    document: RegisteredDocument
    # Sello privado: solo quote_for_fact lo pone; el puente rechaza resultados sin el.
    _seal: object = field(default=None, repr=False, compare=False)


_SEAL = object()


def is_issued_by_pipeline(out: object) -> bool:
    return isinstance(out, PipelineResult) and out._seal is _SEAL


def _extractor_id() -> str:
    import pypdf

    return f"pypdf=={pypdf.__version__}"


def _pdf_pages(content: bytes) -> list[str]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(content))
        if len(reader.pages) > MAX_PAGES:
            raise PrimarySourceError(f"PDF con mas de {MAX_PAGES} paginas")
        pages: list[str] = []
        total = 0
        for page in reader.pages:
            piece = page.extract_text() or ""
            total += len(piece)
            if total > MAX_TEXT_CHARS:
                raise PrimarySourceError("Texto extraido demasiado grande")
            pages.append(piece)
        return pages
    except PrimarySourceError:
        raise
    except Exception as exc:
        raise PrimarySourceError("No se pudo extraer texto del PDF") from exc


def fetch_registered_document(
    ticker: str,
    url: str,
    *,
    today: date,
    fetcher: Callable[..., tuple[bytes, str | None, str]] = fetch_public_url,
    page_extractor: Callable[[bytes], list[str]] = _pdf_pages,
) -> RegisteredDocument:
    """Descarga y extrae SOLO un activo registrado exacto con call_date leida."""
    if not is_official_transcript_url(ticker, url):
        raise PrimarySourceError("URL no registrada como transcripcion oficial exacta")
    asset = asset_from_registry(get_entry(ticker), source_url=url)
    if asset is None:
        raise PrimarySourceError("Activo registrado sin fecha de llamada leida")
    try:
        content, ctype, final_url = fetcher(
            url,
            max_bytes=MAX_BYTES,
            timeout=TIMEOUT_SECONDS,
            allowed_url=lambda candidate: candidate == url,
        )
    except ValueError as exc:
        raise PrimarySourceError(str(exc)) from exc
    except Exception as exc:
        raise PrimarySourceError("No se pudo descargar la fuente oficial") from exc
    if final_url != url:
        raise PrimarySourceError("La descarga termino en una URL distinta de la registrada")
    if (ctype or "").split(";")[0].strip().lower() != "application/pdf":
        raise PrimarySourceError("Content-Type no es application/pdf")
    if not content.startswith(b"%PDF"):
        raise PrimarySourceError("La fuente no es un PDF")
    pages = page_extractor(content)
    text = "\f".join(pages)
    if len(text.split()) < 200:
        raise PrimarySourceError("Texto extraido insuficiente (PDF escaneado o vacio)")
    return RegisteredDocument(
        asset=asset,
        url=url,
        bytes_sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        extractor=_extractor_id(),
        fetched_on=today,
    )


def quote_for_fact(
    *,
    tenant_id: int,
    company_id: int,
    document: RegisteredDocument,
    fact: ReportedObservation,
    today: date,
) -> PipelineResult:
    """La cita sale del adaptador estrecho; el documento ya paso el registro exacto."""
    result = extract_primary_evidence(
        tenant_id=tenant_id,
        company_id=company_id,
        asset=document.asset,
        source_url=document.url,
        original_text=document.text,
        fact=fact,
        today=today,
    )
    return PipelineResult(result=result, document=document, _seal=_SEAL)
