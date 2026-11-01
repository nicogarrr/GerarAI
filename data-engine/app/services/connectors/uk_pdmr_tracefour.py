"""PDMR de Reino Unido via tracefour (gratis, JSON, CC BY 4.0, sin clave).

La SEC no cubre a emisores extranjeros (FPI exentos de la Seccion 16): para el
Reino Unido, los movimientos de insiders (PDMR) llegan por RNS al NSM de la
FCA y tracefour los sirve agregados en JSON. Verificado en vivo el 20/10/2026:
``GET https://tracefour.com/v1/eu/uk`` -> {"data": [...]} con filingId,
publicationAt, issuerName, pdmrName, capacity, transactionNature, isin,
transactionDate, volume, pricePerShare, currency, totalValue, rawArtefactUrl
(enlace al documento original en data.fca.org.uk) y valueUnknown.

Reglas: la ventana del servicio es de ~90 dias, asi que la historia se
ACUMULA en base de datos (idempotente por filingId); el enlace al documento
original de la FCA se conserva siempre; atribucion visible (CC BY 4.0).
Sin clave ni scraping; limite publicado: 60 req/h/IP (una corrida = 1 GET).
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from app.services.data_source_health import get_data_source_registry

TRACEFOUR_URL = "https://tracefour.com/v1/eu/uk"
_REGISTRY_KEY = "tracefour"
SOURCE_NAME = "tracefour"
LICENCE = "CC BY 4.0"
PARSER_VERSION = "tracefour-1"
FORM = "PDMR"
TIMEOUT_SECONDS = 30

_BUY_HINTS = ("acquisition", "acquire", "purchase")
_SELL_HINTS = ("disposal", "sale", "sell")
# Flujos mecanicos que NO son senal de compra/venta (fail-closed, objecion del
# auditor con los casos reales del feed): dividendos/DRIP, suscripcion y
# placing, awards/grants/exercise/vesting, traspasos entre cuentas propias
# (bed & ISA), planes de compra de empleados no discrecionales, adquisiciones
# nocionales y ofertas de recompra complejas.
_NEUTRAL_HINTS = (
    "dividend",
    "drip",
    "subscription",
    "placing",
    "award",
    "grant",
    "exercise",
    "vest",
    "bed & isa",
    "bed and isa",
    "stock purchase plan",
    "savings plan",
    "dcsp",
    "notional",
    "tender offer",
)


async def fetch_pdmr_feed(client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    """Un GET: la lista completa de movimientos recientes (sin parametros)."""
    try:
        if client is not None:
            response = await client.get(TRACEFOUR_URL)
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as owned:
                response = await owned.get(TRACEFOUR_URL)
    except httpx.TransportError as exc:
        get_data_source_registry().record_failure(_REGISTRY_KEY, f"error de red: {type(exc).__name__}")
        raise
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Endpoint fijo sin parámetros: un 404 aquí es que el endpoint se movió
        # (deriva de la fuente), no un recurso por consulta. Degrada.
        get_data_source_registry().record_failure(_REGISTRY_KEY, f"HTTP {exc.response.status_code}")
        raise
    try:
        payload = response.json()
    except ValueError:
        get_data_source_registry().record_failure(_REGISTRY_KEY, "200 sin JSON válido (parse failed)")
        raise
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        get_data_source_registry().record_failure(_REGISTRY_KEY, "200 sin lista 'data' (parse failed)")
        raise RuntimeError("tracefour devolvio una forma inesperada (sin lista 'data')")
    # Éxito solo tras validar la envoltura {"data": [...]}: un 200 no basta.
    get_data_source_registry().record_success(_REGISTRY_KEY)
    return payload["data"]


def map_transaction_code(nature: str | None) -> str | None:
    """Compra/venta al estilo Form 4 ('P'/'S'); fail-closed: lo mecanico o
    ambiguo queda None (nunca una senal falsa)."""
    text = (nature or "").lower()
    if not text.strip() or any(hint in text for hint in _NEUTRAL_HINTS):
        return None
    has_buy = any(hint in text for hint in _BUY_HINTS)
    has_sell = any(hint in text for hint in _SELL_HINTS)
    if has_buy and has_sell:
        return None  # movimiento mixto (p. ej. venta + compra en ISA)
    if has_sell:
        return "S"
    if has_buy:
        return "P"
    return None


def normalize_price(price: Any, currency: str | None) -> tuple[float | None, str | None, bool]:
    """Divisa declarada siempre; nunca se asume (93/307 movimientos del feed
    real llegan SIN divisa: 158 GBP, 47 USD, 9 EUR y el resto sin informar,
    medido el 20/10/2026). Si el PRECIO viene en peniques (GBX/GBp), a libras:
    conversion NO VERIFICADA contra datos reales (ningun movimiento del feed
    la usa hoy); solo al precio, nunca a totalValue (no hay prueba de su
    unidad). Un precio sin divisa se devuelve tal cual con divisa None: la UI
    declara "divisa no informada", nunca asume GBP.
    """
    if not isinstance(price, (int, float)):
        return None, currency, False
    if currency in {"GBX", "GBp", "GBp."}:
        return round(float(price) / 100.0, 6), "GBP", True
    return float(price), currency, False


def fingerprint(filing_id: str) -> str:
    return hashlib.sha256(f"tracefour:{filing_id}".encode()).hexdigest()[:64]


def map_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Un movimiento tracefour -> fila interna; None si le falta identidad."""
    filing_id = str(entry.get("filingId") or "").strip()
    isin = str(entry.get("isin") or "").strip().upper()
    if not filing_id or not isin:
        return None
    price, currency, from_pence = normalize_price(entry.get("pricePerShare"), entry.get("currency"))
    value = entry.get("totalValue")
    value_raw: float | None = None
    if isinstance(value, (int, float)) and from_pence:
        # totalValue en GBX sin verificar: NO se divide; se guarda el bruto
        # solo en data_quality y el importe queda N/D.
        value_raw = float(value)
        value = None
    return {
        "filing_id": filing_id,
        "accession_number": filing_id,
        "form": FORM,
        "isin": isin,
        "issuer_name": entry.get("issuerName"),
        "insider": entry.get("pdmrName"),
        "role": None,
        "officer_title": entry.get("capacity"),
        "code": map_transaction_code(entry.get("transactionNature")),
        "transaction_nature": entry.get("transactionNature"),
        "shares": entry.get("volume") if isinstance(entry.get("volume"), (int, float)) else None,
        "price": price,
        "currency": currency,
        "value": float(value) if isinstance(value, (int, float)) else None,
        "value_raw": value_raw,
        "value_unknown": bool(entry.get("valueUnknown")) or value_raw is not None,
        "tx_date": entry.get("transactionDate"),
        "publication_at": entry.get("publicationAt"),
        "source_url": entry.get("rawArtefactUrl"),
        "price_from_pence": from_pence,
    }
