"""Conector Form 4 (insider trading) sobre SEC EDGAR. Gratis, sin API key.

Referencias MIT consultadas (solo lectura, implementacion propia):
- efebiskin/sec-form4-parser: parse tolerante del XML <ownershipDocument>
  (dataclasses tipadas, codigos P/S, agregados purchases/sales) + fetcher
  EDGAR con rate-limit 10 req/s y User-Agent obligatorio.
- MunehisaWada/edgar-form345: Forms 3/4/5 a CSV + agregacion por
  transaction code y master.idx trimestral.

Diseno propio para GerarAI (cero dependencias nuevas, solo stdlib + httpx):
- submissions JSON de data.sec.gov para listar filings Form 4 por CIK.
- parse del XML del documento primario con xml.etree (tolerante a
  campos ausentes, como los filings reales).
- rate-limit SEC: maximo 10 req/s (intervalo minimo 0.1s) + User-Agent
  de contacto desde settings.sec_user_agent. El reloj del rate-limit NO es de
  este modulo sino de ``connectors/base.py``, compartido con ``form13f``: la
  SEC limita por IP/proceso, y con un reloj por modulo los dos conectores se
  creerian libres a la vez.

No se anade ninguna dependencia: NO tocar requirements.txt por esto.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

import httpx

from app.core.config import get_settings

# El ritmo de la SEC es un estado UNICO de proceso (ver connectors/base.py):
# data.sec.gov limita por IP, no por modulo, asi que un reloj propio aqui
# permitiria que un fetch 13F y un Form 4 disparasen juntos y la SEC devolviese
# 403 a los dos. ``form13f`` comparte este mismo throttle.
from app.services.connectors.base import SEC_MIN_INTERVAL_SECONDS, sec_throttle
from app.services.data_source_health import get_data_source_registry

# Clave compartida con el resto de conectores SEC (sec.py, sec_edgar.py):
# mismo proveedor, mismo circuito. 400/404 (CIK o documento inexistente) son
# dato por emisor y NO degradan; 403/429/5xx/red/no-JSON SI.
_REGISTRY_KEY = "sec_edgar"


def _record_sec_outcome(registry, started: float) -> None:
    registry.record_success(_REGISTRY_KEY, (time.perf_counter() - started) * 1000)


def _record_sec_http_failure(registry, exc) -> None:
    registry.record_failure(_REGISTRY_KEY, f"HTTP {exc.response.status_code}")


def _record_sec_transport_failure(registry, exc: Exception) -> None:
    registry.record_failure(_REGISTRY_KEY, f"error de red: {type(exc).__name__}")


SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

# SEC fair-use: maximo 10 peticiones/segundo.
MIN_INTERVAL_SECONDS = SEC_MIN_INTERVAL_SECONDS

# Alias directo (no un wrapper) para que ``form4._throttle`` y
# ``form13f._throttle`` sean el MISMO objeto y compartan estado por construccion.
_throttle = sec_throttle


BROWSER_USER_AGENT = "Mozilla/5.0 (compatible; GerarAI/0.1; +mailto:{contact}) GerarAI Research"
DEFAULT_CONTACT = "contact@example.com"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def resolve_user_agent() -> str:
    """User-Agent tipo navegador con contacto.

    La SEC bloquea con 403 los User-Agent de producto aunque lleven contacto
    (verificado en prod: ``<producto>/0.1 <email>`` -> 403; UA tipo navegador ->
    200). Misma politica que ``connectors/sec_edgar.py``: se envuelve el
    contacto en un UA tipo navegador, salvo que el operador ya configure uno.
    """
    candidate = (get_settings().sec_user_agent or "").strip()
    if candidate.startswith("Mozilla/"):
        return candidate
    match = _EMAIL_RE.search(candidate)
    contact = match.group(0) if match else DEFAULT_CONTACT
    # Env historico sin espacio ("<producto>/0.1email@..."): la version queda
    # pegada al local-part del email; se retira un prefijo de version.
    contact = re.sub(r"^\d+(\.\d+)+(?=\D)", "", contact)
    return BROWSER_USER_AGENT.format(contact=contact)


def default_headers() -> dict[str, str]:
    return {
        "User-Agent": resolve_user_agent(),
        "Accept": "application/json, text/xml, */*",
        "Accept-Encoding": "gzip, deflate",
    }


def _pad_cik(cik: str | int) -> str:
    return str(cik).strip().zfill(10)


def filing_index_url(cik: str | int, accession_number: str) -> str:
    cik_number = str(int(str(cik).strip()))
    accession = str(accession_number).replace("-", "")
    return f"{ARCHIVES_URL}/{cik_number}/{accession}/"


def recent_form4_filings(
    cik: str | int,
    *,
    limit: int = 20,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Filings Form 4 recientes desde el submissions JSON (sincrono)."""
    url = SUBMISSIONS_URL.format(cik=_pad_cik(cik))
    # Cabeceras ANTES del throttle: el sello del intervalo se fija justo antes de
    # salir a la red. Preparar despues (el primer ``get_settings()`` cuesta
    # ~15 ms) se comia parte del hueco y acortaba la separacion real entre
    # peticiones, que es justo lo que la SEC mide.
    headers = default_headers()
    registry = get_data_source_registry()
    started = time.perf_counter()
    _throttle()
    try:
        if client is not None:
            response = client.get(url, headers=headers)
        else:
            with httpx.Client(timeout=30, headers=headers) as owned:
                response = owned.get(url)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 404):
            raise  # CIK sin datos: dato por emisor, no fuente caida
        _record_sec_http_failure(registry, exc)
        raise
    except httpx.TransportError as exc:
        _record_sec_transport_failure(registry, exc)
        raise
    except ValueError:
        registry.record_failure(_REGISTRY_KEY, "respuesta no JSON")
        raise
    _record_sec_outcome(registry, started)
    recent = (payload.get("filings") or {}).get("recent") or {}
    accessions = recent.get("accessionNumber", []) or []
    cik_number = str(int(str(cik).strip()))
    items: list[dict] = []

    def _col(name: str, index: int):
        values = recent.get(name, []) or []
        return values[index] if index < len(values) else None

    for index, accession in enumerate(accessions):
        form = str(_col("form", index) or "").strip().upper()
        # Form 4 y sus enmiendas (4/A). Las enmiendas corrigen un filing
        # previo; excluirlas dejaba correcciones invisibles.
        if form not in {"4", "4/A"}:
            continue
        primary = _col("primaryDocument", index)
        accession_nodash = str(accession).replace("-", "")
        index_url = f"{ARCHIVES_URL}/{cik_number}/{accession_nodash}/"
        items.append(
            {
                "form": form,
                "accession_number": accession,
                "filing_date": _col("filingDate", index),
                "report_date": _col("reportDate", index),
                "primary_document": primary,
                "index_url": index_url,
                "document_url": f"{index_url}{primary}" if primary else index_url,
            }
        )
        if len(items) >= limit:
            break
    return items


_RENDERED_XSL_RE = re.compile(r"/xslF345X\d+/", re.IGNORECASE)


def raw_document_url(document_url: str) -> str:
    """URL del documento CRUDO a partir de la de EDGAR.

    El submissions JSON apunta `primaryDocument` a la version renderizada
    para humanos (…/xslF345Xnn/form4.xml), que es HTML y revienta el parser
    (F310: el 100% de los Form 4 de un emisor fallaba al leerse). El XML
    crudo vive en el directorio del filing con el mismo nombre de archivo.
    Si la URL no es una variante renderizada, se devuelve tal cual.
    """
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(document_url)
    match = _RENDERED_XSL_RE.search(parsed.path)
    if not match:
        return document_url
    raw_path = parsed.path[: match.start()] + "/" + parsed.path[match.end() :]
    return urlunparse(parsed._replace(path=raw_path))


def _looks_like_xml(text: str) -> bool:
    """XML con o sin declaracion `<?xml`; la version renderizada XSLT es HTML
    (<!DOCTYPE html> / <html) y eso es lo unico que hay que descartar."""
    head = text.lstrip()[:200].lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        return False
    return head.startswith("<")


RETRY_STATUSES = {403, 429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = (2.0, 6.0)


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def _get_text(url: str, client: httpx.Client | None) -> str:
    """GET con backoff ante 403/429/5xx de la SEC (limite por IP): hasta 3 intentos."""
    headers = default_headers()
    attempt = 0
    while True:
        _throttle()
        try:
            if client is not None:
                response = client.get(url, headers=headers)
            else:
                with httpx.Client(timeout=30, headers=headers) as owned:
                    response = owned.get(url)
        except httpx.TransportError as exc:
            _record_sec_transport_failure(get_data_source_registry(), exc)
            raise
        if getattr(response, "status_code", 200) in RETRY_STATUSES and attempt < len(RETRY_BACKOFF_SECONDS):
            _sleep(RETRY_BACKOFF_SECONDS[attempt])
            attempt += 1
            continue
        registry = get_data_source_registry()
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 404):
                raise  # documento inexistente: dato por emisor
            _record_sec_http_failure(registry, exc)
            raise
        _record_sec_outcome(registry, time.perf_counter())
        return response.text


def fetch_filing_xml(
    document_url: str,
    *,
    client: httpx.Client | None = None,
) -> str:
    """Descarga el XML del documento primario (solo hosts sec.gov).

    Si la URL servida es la version renderizada en HTML (xslF345Xnn), se
    reintenta con el documento crudo del mismo directorio (F310).
    """
    from urllib.parse import urlparse

    hostname = (urlparse(document_url).hostname or "").lower()
    if hostname not in {"sec.gov", "www.sec.gov"}:
        raise ValueError("Form 4 document URL must use sec.gov")
    text = _get_text(document_url, client)
    if _looks_like_xml(text):
        return text
    raw_url = raw_document_url(document_url)
    if raw_url == document_url:
        raise ValueError("Form 4 document is not XML and has no raw variant")
    raw_text = _get_text(raw_url, client)
    if not _looks_like_xml(raw_text):
        raise ValueError("Form 4 raw document is not XML either")
    return raw_text


# ---------------- Parse del XML <ownershipDocument> ----------------

_RULE_10B51_RE = re.compile(r"10b5-?1", re.IGNORECASE)


def _footnotes(root: ET.Element) -> dict[str, str]:
    """Notas al pie del documento, id -> texto (ahi vive el «pursuant to a
    Rule 10b5-1 trading plan» de las ventas planificadas)."""
    notes: dict[str, str] = {}
    for note in root.findall("footnotes/footnote"):
        note_id = (note.get("id") or "").strip()
        if note_id and note.text and note.text.strip():
            notes[note_id] = note.text.strip()
    return notes


def _rule_10b5_1(node: ET.Element, footnotes: dict[str, str]) -> bool:
    """True si la transaccion se declara bajo un plan 10b5-1.

    Dos vias, las dos declaradas por el propio insider en el filing:
    - el checkbox 10b5-1 del esquema (cualquier elemento cuyo tag lo
      mencione con valor verdadero; el nombre exacto varia por version);
    - una nota al pie REFERENCIADA por esta transaccion que mencione
      10b5-1. Las notas no referenciadas no cuentan: un filing puede
      mezclar operaciones planificadas y discrecionales.
    """
    for elem in node.iter():
        if "10b5" in elem.tag.lower() and elem.text and elem.text.strip() in {"1", "true", "True"}:
            return True
    for ref in node.iter("footnoteId"):
        note = footnotes.get((ref.get("id") or "").strip())
        if note and _RULE_10B51_RE.search(note):
            return True
    return False


def _text(elem: ET.Element | None, path: str) -> str | None:
    if elem is None:
        return None
    node = elem.find(path)
    if node is None:
        return None
    if node.text and node.text.strip():
        return node.text.strip()
    value = node.find("value")
    if value is not None and value.text and value.text.strip():
        return value.text.strip()
    return None


def _decimal(elem: ET.Element | None, path: str) -> Decimal | None:
    raw = _text(elem, path)
    if raw is None:
        return None
    try:
        return Decimal(raw.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def _date(elem: ET.Element | None, path: str) -> date | None:
    raw = _text(elem, path)
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _flag(elem: ET.Element | None, path: str) -> bool:
    raw = _text(elem, path)
    return raw is not None and raw.strip() in {"1", "true", "True"}


def parse_form4_xml(source: str | bytes) -> dict:
    """Parsea un Form 4 XML a dict con ticker, insider, rol, P/S, acciones, precio, valor.

    Tolerante a campos ausentes (los filings reales omiten hojas opcionales).
    Lanza ValueError si el XML no es un <ownershipDocument>.
    """
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        raise ValueError(f"malformed Form 4 XML: {exc}") from exc
    if root.tag != "ownershipDocument":
        raise ValueError(f"expected root <ownershipDocument>, got <{root.tag}>")

    issuer = root.find("issuer")
    ticker = _text(issuer, "issuerTradingSymbol")
    issuer_name = _text(issuer, "issuerName") or ""
    issuer_cik = _text(issuer, "issuerCik") or ""
    period = _date(root, "periodOfReport")

    footnotes = _footnotes(root)

    reporters: list[dict] = []
    for node in root.findall("reportingOwner"):
        rid = node.find("reportingOwnerId")
        rel = node.find("reportingOwnerRelationship")
        reporters.append(
            {
                "cik": _text(rid, "rptOwnerCik") or "",
                "name": _text(rid, "rptOwnerName") or "",
                "is_director": _flag(rel, "isDirector"),
                "is_officer": _flag(rel, "isOfficer"),
                "is_ten_percent_owner": _flag(rel, "isTenPercentOwner"),
                "officer_title": _text(rel, "officerTitle"),
            }
        )

    def _role(rep: dict) -> str:
        parts = []
        if rep["is_director"]:
            parts.append("director")
        if rep["is_officer"]:
            title = rep.get("officer_title")
            parts.append(f"officer ({title})" if title else "officer")
        if rep["is_ten_percent_owner"]:
            parts.append("10% owner")
        return ", ".join(parts) or "insider"

    transactions: list[dict] = []
    tables = [
        (False, root.findall("nonDerivativeTable/nonDerivativeTransaction")),
        (True, root.findall("derivativeTable/derivativeTransaction")),
    ]
    # Caso general: un Form 4 trae un solo reporter y todas las filas son suyas.
    # Multi-reporter (filing conjunto): el XML NO ata filas a reporters, asi
    # que nunca se atribuye en silencio al primero — se marca la transaccion
    # como filing conjunto y se listan todos los reporters.
    main_rep = (reporters or [{}])[0]
    multi_reporter = len(reporters) > 1
    if multi_reporter:
        joint_names = " / ".join(rep.get("name", "") for rep in reporters if rep.get("name"))
    for is_derivative, nodes in tables:
        for node in nodes:
            coding = node.find("transactionCoding")
            amounts = node.find("transactionAmounts")
            code = (_text(coding, "transactionCode") or "").strip().upper() or None
            acquired = (_text(amounts, "transactionAcquiredDisposedCode") or "").strip().upper() or None
            shares = _decimal(amounts, "transactionShares")
            price = _decimal(amounts, "transactionPricePerShare")
            value = None
            if shares is not None and price is not None:
                value = shares * price
            tx_date = _date(node, "transactionDate")
            transactions.append(
                {
                    "ticker": ticker,
                    "issuer_name": issuer_name,
                    "issuer_cik": issuer_cik,
                    "period_of_report": period.isoformat() if period else None,
                    "insider": joint_names if multi_reporter else main_rep.get("name", ""),
                    "insider_cik": "" if multi_reporter else main_rep.get("cik", ""),
                    "multi_reporter": multi_reporter,
                    "reporters_count": len(reporters),
                    "attribution": "joint_filing" if multi_reporter else "single_reporter",
                    "role": (
                        "multiple insiders"
                        if multi_reporter
                        else (_role(main_rep) if reporters else "insider")
                    ),
                    "officer_title": main_rep.get("officer_title"),
                    "is_officer": bool(main_rep.get("is_officer")),
                    "type": code,  # codigo SEC crudo: P = compra (mercado abierto O privada), S = venta
                    "acquired_disposed": acquired,  # A / D
                    "shares": float(shares) if shares is not None else None,
                    "price": float(price) if price is not None else None,
                    "value": float(value) if value is not None else None,
                    "date": tx_date.isoformat() if tx_date else None,
                    "is_derivative": is_derivative,
                    # RSU vs PSU: dos concesiones del mismo tamano no son duplicados.
                    "security_title": (_text(node, "securityTitle/value") or "").strip() or None,
                    "rule_10b5_1": _rule_10b5_1(node, footnotes),
                }
            )

    return {
        "ticker": ticker,
        "issuer_name": issuer_name,
        "issuer_cik": issuer_cik,
        "period_of_report": period.isoformat() if period else None,
        "reporters": reporters,
        "transactions": transactions,
    }


def is_open_market_buy(tx: dict) -> bool:
    """Compra insider por codigo P + adquirida (A).

    OJO: el codigo P de la SEC cubre compras en mercado abierto Y compras
    privadas; el XML no siempre lo distingue. El nombre de la funcion se
    mantiene por compatibilidad, pero las cadenas visibles al usuario deben
    decir "compra (codigo P: mercado abierto o privado)".
    """
    return tx.get("type") == "P" and tx.get("acquired_disposed") == "A"
