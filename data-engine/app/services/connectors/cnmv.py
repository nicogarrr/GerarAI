"""CNMV connector — official Spanish securities regulator (free, no key).

Verified 2026-09-22 (S1 gate):
- Legal: public official data cataloged on datos.gob.es; CNMV legal notice
  permits reproduction with attribution.
- Technical: NO API. The OIR listing accepts a simple GET with ?dias=N and
  returns server-rendered HTML (one request covers every issuer for a day).
- Cadence: intraday publication; we poll daily (conservative).
- Rate limits: undocumented -> max 1 request per call site, small page budget.
- Failure: any parse drift or HTTP error raises; the caller converts that
  into an honest degraded/unavailable state. Data is NEVER fabricated.

Provenance: source_kind=official (regulator), source_url per document.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.services.data_source_health import get_data_source_registry

_REGISTRY_KEY = "cnmv"
from lxml import html as lxml_html

OIR_RESULTS_URL = "https://www.cnmv.es/portal/otra-informacion-relevante/resultado-oir"
ENTITY_PAGE_URL = "https://www.cnmv.es/portal/consultas/datosentidad.aspx"
MADRID = ZoneInfo("Europe/Madrid")
_USER_AGENT = "GerarAI/1.0 (research; contact: single-user app)"
_MIN_INTERVAL_S = 1.0
_last_request_at = 0.0

_REG_N = re.compile(r"Número de registro:\s*(\d+)")
_NIF_RE = re.compile(r"nif=([A-Z0-9-]+)", re.IGNORECASE)
_MAX_DAYS = 30


class CNMVParseError(RuntimeError):
    """The CNMV page structure drifted; caller must degrade honestly."""


def _throttle() -> None:
    global _last_request_at
    wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def parse_oir_results(page_html: str) -> list[dict]:
    """Parse the OIR results page into normalized filing dicts.

    Structure (verified against the live page 2026-09-22): a repeater of
    first-level <li> blocks, each carrying date, time, entity link (with
    nif= in href), category, document link and registration number.
    Returns an empty list on a valid no-filings day (weekend, holiday):
    the results container renders empty. Raises CNMVParseError only when the
    container itself is missing or a block is incomplete (structural drift).
    """
    try:
        tree = lxml_html.fromstring(page_html)
    except Exception as exc:  # lxml ParserError on empty/broken documents
        raise CNMVParseError(f"unparseable document: {type(exc).__name__}") from exc
    blocks = tree.xpath('//li[contains(concat(" ", normalize-space(@class), " "), " blocks-single ")]')
    if not blocks:
        # Un dia sin hechos relevantes (fin de semana, festivo) NO es deriva:
        # la lista de resultados (<ul id="listaElementosPrimernivel">, verificado
        # contra la pagina viva el 2026-10-31) se renderiza igualmente, vacia.
        # Solo si el contenedor falta la estructura ha cambiado de verdad.
        container = tree.xpath('//ul[@id="listaElementosPrimernivel"]')
        if container:
            return []
        raise CNMVParseError("results list container not found (page structure changed)")
    filings: list[dict] = []
    for block in blocks:
        date_nodes = block.xpath('.//li[contains(@class, "fecha-con-hora")]')
        time_nodes = block.xpath('.//li[contains(@class, "time")]')
        entity_links = block.xpath('.//a[contains(@href, "datosentidad.aspx")]')
        doc_links = block.xpath('.//a[contains(@href, "verdocumento")]')
        cat_nodes = block.xpath('.//span[contains(@class, "negrita")]')
        if not (date_nodes and entity_links and doc_links):
            raise CNMVParseError("incomplete result block (structure drift)")
        raw_date = date_nodes[0].text_content().strip()
        raw_time = time_nodes[0].text_content().strip() if time_nodes else "00:00"
        try:
            published = datetime.strptime(f"{raw_date} {raw_time}", "%d/%m/%Y %H:%M").replace(tzinfo=MADRID)
        except ValueError as exc:
            raise CNMVParseError(f"unparseable date/time: {raw_date!r} {raw_time!r}") from exc
        href = entity_links[0].get("href", "")
        nif_match = _NIF_RE.search(href)
        if not nif_match:
            raise CNMVParseError(f"entity link without nif: {href!r}")
        reg_match = _REG_N.search(block.text_content())
        doc_href = doc_links[0].get("href", "")
        if doc_href.startswith("/"):
            doc_href = "https://www.cnmv.es" + doc_href
        filings.append(
            {
                "entity_name": entity_links[0].text_content().strip(),
                "nif": nif_match.group(1).upper(),
                "entity_url": f"{ENTITY_PAGE_URL}?nif={nif_match.group(1)}",
                "category": cat_nodes[0].text_content().strip() if cat_nodes else None,
                "title": doc_links[0].text_content().strip(),
                "document_url": doc_href,
                "registration_number": reg_match.group(1) if reg_match else None,
                "published_at": published.isoformat(),
            }
        )
    return filings


async def fetch_oir_filings(*, days: int = 1, client: httpx.AsyncClient | None = None) -> list[dict]:
    """Fetch OIR filings for the last N days (one GET; CNMV has no API).

    Registra el outcome en el registry de salud de fuentes: la CNMV es HTML
    scrapeado sin API, justo el caso "el proveedor cambia el HTML" de la
    auditoria — un CNMVParseError (estructura distinta) o un bloqueo deben
    mover el circuito, no quedar invisibles.
    """
    if not 1 <= days <= _MAX_DAYS:
        raise ValueError(f"days must be 1..{_MAX_DAYS}")
    _throttle()
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=30, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
    )
    registry = get_data_source_registry()
    started = time.perf_counter()
    try:
        response = await client.get(OIR_RESULTS_URL, params={"dias": days, "lang": "es"})
        response.raise_for_status()
        filings = parse_oir_results(response.text)
    except httpx.HTTPStatusError as exc:
        registry.record_failure(_REGISTRY_KEY, f"HTTP {exc.response.status_code}")
        raise
    except httpx.TransportError as exc:
        registry.record_failure(_REGISTRY_KEY, f"error de red: {type(exc).__name__}")
        raise
    except CNMVParseError:
        registry.record_failure(_REGISTRY_KEY, "estructura de la pagina cambio")
        raise
    finally:
        if owns_client:
            await client.aclose()
    registry.record_success(_REGISTRY_KEY, (time.perf_counter() - started) * 1000)
    return filings
