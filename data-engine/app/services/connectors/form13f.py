"""Conector Form 13F (institutional holdings) sobre SEC EDGAR. Gratis, sin API key.

- submissions JSON de data.sec.gov para listar 13F-HR / 13F-HR/A por CIK de manager.
- index.json del filing para localizar el information table XML.
- parse tolerante del XML con xml.etree (local-name; campos ausentes -> None).
- rate-limit SEC: 10 req/s + User-Agent de contacto (mismo contrato que form4).
  El throttle y el estado NO se redefinen aqui: se importan de ``form4`` /
  ``connectors/base.py`` porque la SEC limita por IP/proceso. Con un reloj
  propio, un fetch 13F y un Form 4 seguidos creerian ambos que ha pasado su
  intervalo y disparar a la vez -> 403 de la SEC en los dos.
- Enmiendas (13F-HR/A): accession propio e inmutable; nunca se reescribe un
  filing previo.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET  # nosec B314  # stdlib solo para tipos (Element) y ParseError: defusedxml no los exporta; el parseo usa defusedxml

import httpx

# XML externo (SEC EDGAR): defusedxml solo para PARSEAR.
from defusedxml import ElementTree as DefusedET

# Unica definicion de la URL de submissions (la de form4) y UN unico estado de
# throttle, el de connectors/base.py.
from app.services.connectors.base import SEC_MIN_INTERVAL_SECONDS, sec_throttle
from app.services.connectors.form4 import SUBMISSIONS_URL, default_headers, filing_index_url
from app.services.data_source_health import get_data_source_registry

MIN_INTERVAL_SECONDS = SEC_MIN_INTERVAL_SECONDS
FORMS = {"13F-HR", "13F-HR/A"}

# Alias directo al throttle compartido (ver form4._throttle).
_throttle = sec_throttle


# Clave compartida con el resto de conectores SEC (sec.py, sec_edgar.py):
# mismo proveedor, mismo circuito. 400/404 (CIK o documento inexistente) son
# dato por emisor y NO degradan; 403/429/5xx/red/no-JSON SI.
_REGISTRY_KEY = "sec_edgar"


def _record_sec_outcome(registry, started: float) -> None:
    registry.record_success(_REGISTRY_KEY, (time.perf_counter() - started) * 1000)


def _record_sec_http_failure(registry, exc) -> None:
    from app.services.connectors.sec_pacing import rate_limited

    rate_limited(exc.response)
    registry.record_failure(_REGISTRY_KEY, f"HTTP {exc.response.status_code}")


def _record_sec_transport_failure(registry, exc: Exception) -> None:
    registry.record_failure(_REGISTRY_KEY, f"error de red: {type(exc).__name__}")


def _get(url: str, client: httpx.Client | None) -> httpx.Response:
    # Cabeceras antes del throttle (ver form4.recent_form4_filings): el sello
    # del intervalo debe fijarse lo mas pegado posible a la salida a la red.
    headers = default_headers()
    registry = get_data_source_registry()
    _throttle()
    try:
        if client is not None:
            response = client.get(url, headers=headers)
        else:
            with httpx.Client(timeout=30, headers=headers) as owned:
                response = owned.get(url)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 404):
            raise  # CIK/documento inexistente: dato por emisor
        _record_sec_http_failure(registry, exc)
        raise
    except httpx.TransportError as exc:
        _record_sec_transport_failure(registry, exc)
        raise
    # Sin éxito aquí: un 200 no basta (puede ser un challenge HTML). El éxito
    # lo registra el consumidor tras validar el formato (JSON o XML).
    return response


def recent_13f_filings(
    cik: str | int,
    *,
    limit: int = 8,
    client: httpx.Client | None = None,
) -> list[dict]:
    """13F-HR y 13F-HR/A recientes del manager, mas reciente primero."""
    url = SUBMISSIONS_URL.format(cik=str(cik).strip().zfill(10))
    registry = get_data_source_registry()
    started = time.perf_counter()
    try:
        payload = _get(url, client).json()
    except ValueError:
        registry.record_failure(_REGISTRY_KEY, "200 sin JSON válido (parse failed)")
        raise
    if not isinstance(payload, dict) or "filings" not in payload:
        # Un 200 con JSON lista o {} no es el submissions de la SEC.
        registry.record_failure(_REGISTRY_KEY, "200 con JSON sin la clave 'filings' (parse failed)")
        raise ValueError("13F submissions payload is not the SEC submissions object")
    _record_sec_outcome(registry, started)
    recent = (payload.get("filings") or {}).get("recent") or {}
    accessions = recent.get("accessionNumber", []) or []
    items: list[dict] = []

    def _col(name: str, index: int):
        values = recent.get(name, []) or []
        return values[index] if index < len(values) else None

    for index, accession in enumerate(accessions):
        form = str(_col("form", index) or "").strip().upper()
        if form not in FORMS:
            continue
        items.append(
            {
                "accession_number": accession,
                "form": form,
                "is_amendment": form.endswith("/A"),
                "report_date": _col("reportDate", index),
                "filing_date": _col("filingDate", index),
                "primary_document": _col("primaryDocument", index),
            }
        )
        if len(items) >= limit:
            break
    return items


def information_table_url(
    cik: str | int,
    accession_number: str,
    primary_document: str | None,
    *,
    client: httpx.Client | None = None,
) -> str | None:
    """URL del information table XML dentro del filing; None si no se localiza."""
    base = filing_index_url(cik, accession_number)
    registry = get_data_source_registry()
    started = time.perf_counter()
    try:
        payload = _get(f"{base}index.json", client).json()
    except ValueError:
        registry.record_failure(_REGISTRY_KEY, "200 sin JSON válido (parse failed)")
        raise
    if not isinstance(payload, dict) or "directory" not in payload:
        registry.record_failure(_REGISTRY_KEY, "200 con JSON sin la clave 'directory' (parse failed)")
        raise ValueError("13F index payload is not the SEC directory object")
    _record_sec_outcome(registry, started)
    items = (payload.get("directory") or {}).get("item") or []
    candidates: list[str] = []
    for item in items:
        name = str(item.get("name") or "")
        if not name.lower().endswith(".xml"):
            continue
        # primaryDocument puede venir con carpeta de estilo ("xslForm13F_X02/primary_doc.xml"):
        # se compara el nombre base, y primary_doc.xml nunca es el information table.
        primary_base = (primary_document or "").rsplit("/", 1)[-1]
        if (
            name == primary_document
            or (primary_base and name == primary_base)
            or name.lower() == "primary_doc.xml"
        ):
            continue
        candidates.append(name)
    if not candidates:
        return None

    def _is_info_table(n: str) -> bool:
        flat = n.lower().replace("-", "").replace("_", "")
        return "infotable" in flat or "13f" in flat

    preferred = [n for n in candidates if _is_info_table(n)]
    return base + (preferred[0] if preferred else candidates[0])


def fetch_information_table(url: str, *, client: httpx.Client | None = None) -> list[dict]:
    registry = get_data_source_registry()
    started = time.perf_counter()
    text = _get(url, client).text
    try:
        rows = parse_information_table(text)
    except (ET.ParseError, ValueError):
        registry.record_failure(_REGISTRY_KEY, "200 sin XML válido (parse failed)")
        raise
    _record_sec_outcome(registry, started)
    return rows


def parse_information_table(xml_text: str) -> list[dict]:
    """Filas del information table; local-name, tolerante a campos ausentes."""

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def find_text(elem, name: str) -> str | None:
        for child in elem.iter():
            if local(child.tag) == name:
                return (child.text or "").strip() or None
        return None

    root = DefusedET.fromstring(xml_text)
    if local(root.tag) != "informationTable":
        # Un 200 con HTML bien formado (challenge de WAF) parsea como XML;
        # la raíz oficial del esquema 13F es informationTable.
        raise ValueError("el documento no es un information table 13F")
    rows: list[dict] = []
    for info in root.iter():
        if local(info.tag) != "infoTable":
            continue
        rows.append(
            {
                "name_of_issuer": find_text(info, "nameOfIssuer"),
                "title_of_class": find_text(info, "titleOfClass"),
                "cusip": find_text(info, "cusip"),
                "value_usd_thousands": find_text(info, "value"),
                "ssh_prnamt": find_text(info, "sshPrnamt"),
                "ssh_prnamt_type": find_text(info, "sshPrnamtType"),
                "put_call": find_text(info, "putCall"),
                "investment_discretion": find_text(info, "investmentDiscretion"),
                "voting_sole": find_text(info, "Sole"),
                "voting_shared": find_text(info, "Shared"),
                "voting_none": find_text(info, "None"),
            }
        )
    return rows


def _dec(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def aggregate_rows(rows: list[dict]) -> list[dict]:
    """Une las filas del information table con la misma clave.

    Un 13F real repite (cusip, titulo, put/call) una vez por gestor "other
    manager" o por discrecion. La tabla guarda una fila por clave, asi que se
    SUMAN valor, acciones y votos; del resto se conserva el primer valor no
    vacio. Las filas sin CUSIP se descartan (nunca se inventa uno).

    Limite conocido: la clave NO incluye SH/PRN (acciones vs importe nominal). Si un
    gestor declarase ambos tipos para el mismo CUSIP y titulo, "shares" mezclaria
    unidades; el valor en dolares si es correcto y se verifica contra tableValueTotal.
    """
    summed = ("value_usd_thousands", "ssh_prnamt", "voting_sole", "voting_shared", "voting_none")
    merged: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        cusip = (row.get("cusip") or "").strip()
        if not cusip:
            continue
        key = (cusip, (row.get("title_of_class") or "").strip(), (row.get("put_call") or "").strip())
        current = merged.get(key)
        if current is None:
            merged[key] = dict(row)
            continue
        for name in summed:
            a, b = _dec(current.get(name)), _dec(row.get(name))
            if a is None and b is None:
                continue
            current[name] = str((a or Decimal(0)) + (b or Decimal(0)))
        for name, value in row.items():
            if name not in summed and not current.get(name) and value:
                current[name] = value
    return list(merged.values())


# --- Escala del valor (heuristica, por filing) --------------------------------
# Desde el 2022-12-31 el 13F declara el valor en dolares, pero algunos gestores
# (verificado contra EDGAR: Baupost 0001061768-26-000010, tableValueTotal 5415853
# para una cartera de ~5.4 mil millones) siguen declarando en miles. La columna
# conserva el valor tal cual vino del filing; esta regla detecta la escala SOLO por el
# precio implicito (valor / acciones) de las filas de acciones ordinarias:
#   mediana < 1 USD por accion  =>  el filing esta en miles y se multiplica x1000.
# Es una heuristica, no un dato del filing: se guarda en value_scale cual se uso.
DOLLAR_VALUE_FROM = date(2022, 12, 31)
THOUSANDS_MEDIAN_PRICE_CEILING = Decimal("1")
MIN_PRICED_ROWS = 3
SCALE_DOLLARS = "dollars_raw"
SCALE_THOUSANDS = "thousands_x1000"


def infer_value_scale(rows: list[dict], report_date: str | date | None) -> dict:
    """Escala del valor de un filing: {'scale', 'median_implied_price', 'priced_rows'}.

    Solo se evalua para periodos >= 2022-12-31. Con menos de MIN_PRICED_ROWS filas
    de acciones (SH, sin opciones, valor y acciones > 0) no se decide: se deja el valor
    crudo (SCALE_DOLLARS) y se marca 'insufficient_rows'.
    """
    if isinstance(report_date, str):
        try:
            report_date = date.fromisoformat(report_date)
        except ValueError:
            report_date = None
    if report_date is None or report_date < DOLLAR_VALUE_FROM:
        return {"scale": None, "median_implied_price": None, "priced_rows": 0, "reason": "legacy_period"}
    prices: list[Decimal] = []
    for row in rows:
        if (row.get("ssh_prnamt_type") or "SH").strip().upper() != "SH" or (
            row.get("put_call") or ""
        ).strip():
            continue
        value, shares = _dec(row.get("value_usd_thousands")), _dec(row.get("ssh_prnamt"))
        if value is None or shares is None or value <= 0 or shares <= 0:
            continue
        prices.append(value / shares)
    if len(prices) < MIN_PRICED_ROWS:
        return {
            "scale": SCALE_DOLLARS,
            "median_implied_price": None,
            "priced_rows": len(prices),
            "reason": "insufficient_rows",
        }
    prices.sort()
    mid = len(prices) // 2
    median = prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2
    scale = SCALE_THOUSANDS if median < THOUSANDS_MEDIAN_PRICE_CEILING else SCALE_DOLLARS
    return {
        "scale": scale,
        "median_implied_price": str(round(median, 4)),
        "priced_rows": len(prices),
        "reason": "median_implied_price",
    }


def apply_value_scale(rows: list[dict], scale: str | None) -> list[dict]:
    """Copia de las filas con el valor llevado a dolares si la escala es miles."""
    if scale != SCALE_THOUSANDS:
        return rows
    out = []
    for row in rows:
        value = _dec(row.get("value_usd_thousands"))
        out.append({**row, "value_usd_thousands": str(value * 1000) if value is not None else None})
    return out


def parse_primary_summary(xml_text: str) -> dict:
    """tableEntryTotal, tableValueTotal y amendmentType del primary_doc.xml."""

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    found: dict[str, str] = {}
    root = DefusedET.fromstring(xml_text)
    # Raíz oficial del esquema thirteenffiler (ns sec.gov/edgar/thirteenffiler).
    if local(root.tag) != "edgarSubmission":
        raise ValueError("el documento no es un primary_doc 13F")
    for elem in root.iter():
        name = local(elem.tag)
        if name in {"tableEntryTotal", "tableValueTotal", "amendmentType"} and (elem.text or "").strip():
            found.setdefault(name, (elem.text or "").strip())
    entries = _dec(found.get("tableEntryTotal"))
    value = _dec(found.get("tableValueTotal"))
    return {
        "table_entry_total": int(entries) if entries is not None else None,
        "table_value_total": value,
        "amendment_type": found.get("amendmentType"),
    }


def fetch_primary_summary(
    cik: str | int, accession_number: str, *, client: httpx.Client | None = None
) -> dict | None:
    """Resumen declarado por el propio filing; None si no se puede leer."""
    url = filing_index_url(cik, accession_number) + "primary_doc.xml"
    registry = get_data_source_registry()
    started = time.perf_counter()
    try:
        text = _get(url, client).text
    except Exception:  # noqa: BLE001 - sin resumen => "no verificado", nunca inventado
        # Los fallos HTTP/red ya quedaron registrados dentro de _get.
        return None
    try:
        summary = parse_primary_summary(text)
    except (ET.ParseError, ValueError):
        # Formato drift (p.ej. challenge HTML): fuente degradada, pero el
        # contrato "None = no verificado" se mantiene para el llamador.
        registry.record_failure(_REGISTRY_KEY, "200 sin XML válido (parse failed)")
        return None
    _record_sec_outcome(registry, started)
    return summary
