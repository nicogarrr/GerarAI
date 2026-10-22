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
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
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


# --- Ejecucion acotada (job/HTTP): hijo aislado, deadline total, concurrencia y cache ---

import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from collections import OrderedDict  # noqa: E402

TOTAL_DEADLINE_SECONDS = 45.0
CHILD_CPU_SECONDS = 20
CHILD_MEMORY_BYTES = 1_000_000_000
MAX_CHILD_OUTPUT_BYTES = 4 * MAX_TEXT_CHARS
MAX_CONCURRENT = 2
CACHE_TTL_SECONDS = 900.0
CACHE_MAX_ENTRIES = 8

_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT)
_CACHE: OrderedDict[str, tuple[float, RegisteredDocument]] = OrderedDict()
_SEEN_BYTES: dict[str, str] = {}  # url -> sha256 de la ultima descarga observada EN ESTE PROCESO
_LOCK = threading.Lock()


def run_child(argv: list[str], *, deadline: float = TOTAL_DEADLINE_SECONDS) -> dict:
    """Ejecuta un hijo con deadline TOTAL de reloj; mata el proceso al vencer. Salida acotada."""
    try:
        proc = subprocess.run(  # noqa: S603
            argv, capture_output=True, timeout=deadline, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise PrimarySourceError("Tiempo total excedido al obtener la fuente") from exc
    if len(proc.stdout) > MAX_CHILD_OUTPUT_BYTES:
        raise PrimarySourceError("Salida del extractor demasiado grande")
    if proc.returncode != 0:
        raise PrimarySourceError("El extractor aislado fallo (limite de CPU/memoria o error)")
    try:
        data = json.loads(proc.stdout.decode())
    except ValueError as exc:
        raise PrimarySourceError("Respuesta del extractor no valida") from exc
    if not isinstance(data, dict):
        raise PrimarySourceError("Respuesta del extractor no valida")
    return data


def fetch_registered_document_isolated(
    ticker: str, url: str, *, today: date, deadline: float = TOTAL_DEADLINE_SECONDS,
    runner: Callable[..., dict] = run_child,
) -> tuple[RegisteredDocument, dict]:
    """Registro exacto + descarga/extraccion en hijo con limites + dedup por URL.

    Devuelve (documento, meta) con meta = {cache_hit, previous_bytes_sha256, bytes_changed}.
    `bytes_changed` solo compara contra la ultima descarga vista EN ESTE PROCESO; None si no
    hay observacion previa (no es un historial persistente).
    """
    if not is_official_transcript_url(ticker, url):
        raise PrimarySourceError("URL no registrada como transcripcion oficial exacta")
    asset = asset_from_registry(get_entry(ticker), source_url=url)
    if asset is None:
        raise PrimarySourceError("Activo registrado sin fecha de llamada leida")
    if any(a.url == url and a.format == "html" for a in get_entry(ticker).assets):
        return _fetch_html_transcript(ticker, url, asset, today=today, deadline=deadline,
                                      runner=runner)
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(url)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            _CACHE.move_to_end(url)
            return hit[1], {"cache_hit": True, "previous_bytes_sha256": None, "bytes_changed": None}
    if not _SLOTS.acquire(blocking=False):
        raise PrimarySourceError("Demasiadas descargas en curso; reintentar mas tarde")
    try:
        data = runner(
            [sys.executable, "-m", "app.services.commitment_primary_worker", url,
             str(CHILD_CPU_SECONDS), str(CHILD_MEMORY_BYTES)],
            deadline=deadline,
        )
    finally:
        _SLOTS.release()
    if "error" in data:
        raise PrimarySourceError(str(data["error"])[:200])
    pages = data.get("pages")
    sha = data.get("bytes_sha256")
    if (data.get("final_url") != url or data.get("content_type") != "application/pdf"
            or not isinstance(pages, list) or not all(isinstance(p, str) for p in pages)
            or not isinstance(sha, str) or len(sha) != 64):
        raise PrimarySourceError("Respuesta del extractor inconsistente")
    text = "\f".join(pages)
    if len(text.split()) < 200:
        raise PrimarySourceError("Texto extraido insuficiente (PDF escaneado o vacio)")
    doc = RegisteredDocument(
        asset=asset, url=url, bytes_sha256=sha, byte_size=int(data.get("byte_size", 0)),
        text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        extractor=_extractor_id(), fetched_on=today,
    )
    with _LOCK:
        previous = _SEEN_BYTES.get(url)
        _SEEN_BYTES[url] = sha
        _CACHE[url] = (now, doc)
        while len(_CACHE) > CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)
    return doc, {
        "cache_hit": False,
        "previous_bytes_sha256": previous,
        "bytes_changed": None if previous is None else previous != sha,
    }


def fetch_registered_html_isolated(
    url: str, *, deadline: float = TOTAL_DEADLINE_SECONDS, runner: Callable[..., dict] = run_child,
) -> bytes:
    """HTML de un activo FINANCIERO exacto registrado, en el mismo hijo acotado que el PDF
    (CPU/memoria/deadline total de reloj, salida acotada). Sin reescribir la politica SSRF."""
    from app.services.commitment_financial_release import FINANCIAL_ASSETS

    if not any(a.url == url for a in FINANCIAL_ASSETS):
        raise PrimarySourceError("URL no registrada como documento financiero exacto")
    return _run_html_child(url, deadline=deadline, runner=runner)


def _run_html_child(
    url: str, *, deadline: float, runner: Callable[..., dict] = run_child,
) -> bytes:
    import base64

    if not _SLOTS.acquire(blocking=False):
        raise PrimarySourceError("Demasiadas descargas en curso; reintentar mas tarde")
    try:
        data = runner(
            [sys.executable, "-m", "app.services.commitment_primary_worker", url,
             str(CHILD_CPU_SECONDS), str(CHILD_MEMORY_BYTES), "html"],
            deadline=deadline,
        )
    finally:
        _SLOTS.release()
    if "error" in data:
        raise PrimarySourceError(str(data["error"])[:200])
    try:
        content = base64.b64decode(data["html_b64"], validate=True)
    except (KeyError, ValueError, TypeError) as exc:
        raise PrimarySourceError("Respuesta del extractor inconsistente") from exc
    if (data.get("final_url") != url or data.get("content_type") != "text/html"
            or hashlib.sha256(content).hexdigest() != data.get("bytes_sha256")
            or len(content) > 4_000_000):
        raise PrimarySourceError("Respuesta del extractor inconsistente")
    return content


HTML_TRANSCRIPT_MAX_BYTES = 1_500_000


class _TextExtractor(HTMLParser):
    """Texto visible con la libreria estandar: sin scripts/estilos/nav/cabecera/pie (no ejecuta JS)."""

    _SKIP = {"script", "style", "nav", "header", "footer", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):  # noqa: ARG002
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_visible_text(content: bytes) -> str:
    parser = _TextExtractor()
    parser.feed(content.decode("utf-8", "replace"))
    return re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.parts)).replace(" \n", "\n").strip()


def _fetch_html_transcript(
    ticker: str, url: str, asset, *, today: date, deadline: float, runner: Callable[..., dict],
) -> tuple[RegisteredDocument, dict]:
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(url)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            _CACHE.move_to_end(url)
            return hit[1], {"cache_hit": True, "previous_bytes_sha256": None, "bytes_changed": None}
    content = _run_html_child(url, deadline=deadline, runner=runner)
    if len(content) > HTML_TRANSCRIPT_MAX_BYTES:
        raise PrimarySourceError("HTML de transcripcion demasiado grande para el parseo en proceso")
    # OJO: la DESCARGA va en el hijo acotado; este PARSEO corre en el proceso padre.
    text = html_visible_text(content)
    if len(text.split()) < 200:
        raise PrimarySourceError("Texto extraido insuficiente (pagina vacia o requiere JS)")
    sha = hashlib.sha256(content).hexdigest()
    doc = RegisteredDocument(
        asset=asset, url=url, bytes_sha256=sha, byte_size=len(content),
        text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        extractor="html-stdlib", fetched_on=today,
    )
    with _LOCK:
        previous = _SEEN_BYTES.get(url)
        _SEEN_BYTES[url] = sha
        _CACHE[url] = (now, doc)
        while len(_CACHE) > CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)
    return doc, {"cache_hit": False, "previous_bytes_sha256": previous,
                 "bytes_changed": None if previous is None else previous != sha}
