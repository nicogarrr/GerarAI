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

TRACEFOUR_URL = "https://tracefour.com/v1/eu/uk"
SOURCE_NAME = "tracefour"
LICENCE = "CC BY 4.0"
PARSER_VERSION = "tracefour-1"
FORM = "PDMR"
TIMEOUT_SECONDS = 30

_BUY_HINTS = ("acquisition", "purchase", "subscription", "award", "grant", "exercise")
_SELL_HINTS = ("disposal", "sale", "sell", "transfer out")


async def fetch_pdmr_feed(client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    """Un GET: la lista completa de movimientos recientes (sin parametros)."""
    if client is not None:
        response = await client.get(TRACEFOUR_URL)
    else:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as owned:
            response = await owned.get(TRACEFOUR_URL)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError("tracefour devolvio una forma inesperada (sin lista 'data')")
    return payload["data"]


def map_transaction_code(nature: str | None) -> str | None:
    """Compra/venta al estilo Form 4 ('P'/'S'); lo ambiguo queda None (nunca se adivina)."""
    text = (nature or "").lower()
    if any(hint in text for hint in _SELL_HINTS):
        return "S"
    if any(hint in text for hint in _BUY_HINTS):
        return "P"
    return None


def normalize_price(price: Any, currency: str | None) -> tuple[float | None, str | None, bool]:
    """Divisa declarada siempre. Si viene en peniques (GBX/GBp), a libras.

    Devuelve (precio, divisa, normalizado_desde_peniques). Un precio sin
    divisa se devuelve tal cual con divisa None: la UI lo muestra como N/D
    de divisa, nunca asume GBP.
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
    if isinstance(value, (int, float)) and from_pence:
        value = round(float(value) / 100.0, 6)
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
        "value_unknown": bool(entry.get("valueUnknown")),
        "tx_date": entry.get("transactionDate"),
        "publication_at": entry.get("publicationAt"),
        "source_url": entry.get("rawArtefactUrl"),
        "price_from_pence": from_pence,
    }
