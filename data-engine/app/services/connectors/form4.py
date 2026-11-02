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

El transporte EDGAR (submissions JSON, cabeceras, backoff 403/429/5xx,
registro de salud) vive en ``connectors/edgar_common.py``, compartido con
``form13dg`` y ``form13f``: antes form13dg se documentaba como "espejo" de
este modulo copiando la misma logica a mano; ahora el espejo es por
construccion (mismo codigo importado) y no puede desalinearse. Los nombres
publicos se reexportan aqui (alias) para no romper a los consumidores, y los
wrappers inyectan los globales de ESTE modulo (``_throttle``, ``_sleep``,
``default_headers``) en edgar_common para que los monkeypatch de los tests
sigan actuando sobre form4.

No se anade ninguna dependencia: NO tocar requirements.txt por esto.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET  # nosec B314  # stdlib solo para tipos (Element) y ParseError: defusedxml no los exporta; el parseo usa defusedxml

import httpx

# XML externo (SEC EDGAR): defusedxml solo para PARSEAR.
from defusedxml import ElementTree as DefusedET

from app.services.connectors import edgar_common
from app.services.data_source_health import get_data_source_registry

# Transporte EDGAR compartido (ver la docstring de cabecera): alias directos,
# NO wrappers, para que la identidad sea la de edgar_common y los imports
# existentes (form13f, form13dg, tests) sigan funcionando sin cambios.
SUBMISSIONS_URL = edgar_common.SUBMISSIONS_URL
ARCHIVES_URL = edgar_common.ARCHIVES_URL
MIN_INTERVAL_SECONDS = edgar_common.MIN_INTERVAL_SECONDS
_throttle = edgar_common._throttle  # == base.sec_throttle (test_sec_throttle_shared)
resolve_user_agent = edgar_common.resolve_user_agent
default_headers = edgar_common.default_headers
filing_index_url = edgar_common.filing_index_url
RETRY_STATUSES = edgar_common.RETRY_STATUSES
RETRY_BACKOFF_SECONDS = edgar_common.RETRY_BACKOFF_SECONDS
_record_sec_outcome = edgar_common._record_sec_outcome
_record_sec_http_failure = edgar_common._record_sec_http_failure
_record_sec_transport_failure = edgar_common._record_sec_transport_failure


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def _get_text(url: str, client: httpx.Client | None) -> str:
    """GET con backoff ante 403/429/5xx de la SEC (limite por IP): hasta 3 intentos."""
    return edgar_common.get_text(url, client, headers=default_headers(), throttle=_throttle, sleep=_sleep)


def recent_form4_filings(
    cik: str | int,
    *,
    limit: int = 20,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Filings Form 4 recientes desde el submissions JSON (sincrono)."""
    # Form 4 y sus enmiendas (4/A). Las enmiendas corrigen un filing previo;
    # excluirlas dejaba correcciones invisibles.
    return edgar_common.recent_filings(
        cik,
        forms={"4", "4/A"},
        limit=limit,
        client=client,
        headers=default_headers(),
        throttle=_throttle,
    )


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


def _is_form4_xml(text: str) -> bool:
    """Parseo real: solo vale XML bien formado con raíz <ownershipDocument>
    (esquema F345). `<div>AccessDenied</div>` o `<?xml><broken` no pasan."""
    try:
        root = DefusedET.fromstring(text)
    except ET.ParseError:
        return False
    return root.tag.rsplit("}", 1)[-1] == "ownershipDocument"


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
    registry = get_data_source_registry()
    started = time.perf_counter()
    text = _get_text(document_url, client)
    if _is_form4_xml(text):
        _record_sec_outcome(registry, started)
        return text
    raw_url = raw_document_url(document_url)
    if raw_url == document_url:
        registry.record_failure(edgar_common._REGISTRY_KEY, "200 sin XML válido (parse failed)")
        raise ValueError("Form 4 document is not XML and has no raw variant")
    raw_text = _get_text(raw_url, client)
    if not _is_form4_xml(raw_text):
        registry.record_failure(edgar_common._REGISTRY_KEY, "200 sin XML válido (parse failed)")
        raise ValueError("Form 4 raw document is not XML either")
    _record_sec_outcome(registry, started)
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
        root = DefusedET.fromstring(source)
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
