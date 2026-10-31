"""Insiders de Canada via Yahoo quoteSummary (FUENTE NO OFICIAL).

La verdad oficial de insiders canadienses es SEDI (sedi.ca), que prohibe el
scraping y no tiene API publica: NUNCA se scrapea. Yahoo expone
``quoteSummary?modules=insiderTransactions`` (cookie fc.yahoo.com + crumb,
la misma infra que las fechas de resultados) con texto libre por movimiento.

Limites declarados: es fuente NO OFICIAL (asi se etiqueta en la UI, con
enlace a SEDI como verdad manual); NO declara divisa (currency=None siempre:
la UI muestra "divisa no informada"); no trae id de filing (el fingerprint
se deriva del contenido); transactionText es libre -> el mapping compra/
venta es fail-closed (lo mecanico o ambiguo queda None). Datos ilegibles o
ausentes = sin dato con causa, nunca "sin actividad".
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import httpx

from app.services.data_source_health import get_data_source_registry

SOURCE_NAME = "yahoo_quoteSummary"
_REGISTRY_KEY = "yahoo_finance"


def _record_http_failure(exc: httpx.HTTPStatusError) -> None:
    # 400/404: simbolo sin quoteSummary (consulta concreta), no fuente caida.
    if exc.response.status_code in (400, 404):
        return
    get_data_source_registry().record_failure(_REGISTRY_KEY, f"HTTP {exc.response.status_code}")


def _record_transport_failure(exc: Exception) -> None:
    get_data_source_registry().record_failure(_REGISTRY_KEY, f"error de red: {type(exc).__name__}")


PARSER_VERSION = "yahoo-ca-1"
FORM = "CA-INSIDER"
SEDI_URL = "https://www.sedi.ca"


def yahoo_insider_url(symbol: str) -> str:
    """Pagina publica de Yahoo con los movimientos de insiders del valor.

    Es la fuente no oficial del dato; SEDI queda
    en ``data_quality.official_source`` como verdad oficial de consulta manual.
    """
    return f"https://finance.yahoo.com/quote/{symbol}/insider-transactions/"


TIMEOUT_SECONDS = 15
PAUSE_SECONDS = 3.0
QUOTESUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary"

# Nuestros tickers canadienses cubiertos -> simbolo Yahoo (mismo hoy).
CA_TICKERS: dict[str, str] = {"BN": "BN", "KRKNF": "KRKNF"}

_BUY_HINTS = ("acquisition", "purchase", "buy")
_SELL_HINTS = ("sale", "disposition", "sell")
# Flujos mecanicos: no son senal (mismo criterio fail-closed que PDMR UK).
_NEUTRAL_HINTS = (
    "exercise",
    "option",
    "award",
    "grant",
    "vest",
    "dividend",
    "drip",
    "subscription",
    "plan",
    "gift",
    "transfer",
    "conversion",
)


def yahoo_session(client: httpx.Client | None = None) -> tuple[httpx.Client, str]:
    """Cookie fc.yahoo.com + crumb (mismo patron que earnings_dates_service)."""
    owned = client or httpx.Client(
        headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT_SECONDS, follow_redirects=True
    )
    try:
        owned.get("https://fc.yahoo.com")  # 404 esperado: solo fija la cookie
        crumb = owned.get("https://query1.finance.yahoo.com/v1/test/getcrumb").text.strip()
    except httpx.TransportError as exc:
        _record_transport_failure(exc)
        raise
    if not crumb or " " in crumb or len(crumb) > 40:
        # Yahoo bloquea o cambia el flujo de crumb: fuente degradada.
        _record_transport_failure(RuntimeError("yahoo_crumb_unavailable"))
        raise RuntimeError("yahoo_crumb_unavailable")
    return owned, crumb


def fetch_insider_transactions(symbol: str, client: httpx.Client, crumb: str) -> list[dict[str, Any]]:
    """Movimientos crudos de Yahoo para un simbolo; [] si no hay modulo."""
    try:
        response = client.get(
            f"{QUOTESUMMARY_URL}/{symbol}",
            params={"modules": "insiderTransactions", "crumb": crumb},
        )
    except httpx.TransportError as exc:
        _record_transport_failure(exc)
        raise
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _record_http_failure(exc)
        raise
    try:
        payload = response.json()
    except ValueError:
        get_data_source_registry().record_failure(_REGISTRY_KEY, "200 sin JSON válido (parse failed)")
        raise
    if not isinstance(payload, dict) or "quoteSummary" not in payload:
        # Un 200 con JSON lista o sin la envoltura quoteSummary no es el
        # contrato de Yahoo: deriva de formato (challenge, cambio de API).
        get_data_source_registry().record_failure(
            _REGISTRY_KEY, "200 con JSON sin 'quoteSummary' (parse failed)"
        )
        raise ValueError("yahoo quoteSummary payload is not the expected object")
    result = (payload.get("quoteSummary") or {}).get("result") or []
    # Éxito tras validar la envoltura; un símbolo sin módulo es [] válido.
    get_data_source_registry().record_success(_REGISTRY_KEY)
    if not result:
        return []
    module = result[0].get("insiderTransactions") or {}
    transactions = module.get("transactions")
    return transactions if isinstance(transactions, list) else []


def map_transaction_code(text: str | None) -> str | None:
    """'Acquisition in the public market...' -> 'P'; 'Exercise of options...' -> None."""
    low = (text or "").lower()
    if not low.strip() or any(hint in low for hint in _NEUTRAL_HINTS):
        return None
    has_buy = any(hint in low for hint in _BUY_HINTS)
    has_sell = any(hint in low for hint in _SELL_HINTS)
    if has_buy and has_sell:
        return None
    if has_sell:
        return "S"
    if has_buy:
        return "P"
    return None


_PRICE_RE = re.compile(r"at price ([0-9]+(?:\.[0-9]+)?)")


def map_transaction(ticker: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    """Un movimiento Yahoo -> fila interna; None si le falta identidad minima."""
    filer = str(raw.get("filerName") or "").strip()
    start = raw.get("startDate") or {}
    day = start.get("fmt") if isinstance(start, dict) else None
    text = str(raw.get("transactionText") or "").strip()
    if not filer or not day or not text:
        return None
    shares = (raw.get("shares") or {}).get("raw") if isinstance(raw.get("shares"), dict) else None
    value = (raw.get("value") or {}).get("raw") if isinstance(raw.get("value"), dict) else None
    price_match = _PRICE_RE.search(text)
    return {
        "fingerprint": hashlib.sha256(
            f"yahoo-ca:{ticker}:{filer}:{day}:{shares}:{value}:{text}".encode()
        ).hexdigest()[:64],
        "form": FORM,
        "ticker": ticker,
        "insider": filer,
        "role": None,
        "officer_title": raw.get("filerRelation"),
        "code": map_transaction_code(text),
        "transaction_nature": text,
        "shares": float(shares) if isinstance(shares, (int, float)) else None,
        # El precio se extrae del texto libre solo si viene explicito; la
        # divisa NUNCA (Yahoo no la declara): currency=None -> "divisa no
        # informada" en la UI.
        "price": float(price_match.group(1)) if price_match else None,
        "currency": None,
        "value": float(value) if isinstance(value, (int, float)) else None,
        "tx_date": day,
        "ownership": raw.get("ownership"),
        "source_url": yahoo_insider_url(CA_TICKERS.get(ticker, ticker)),
    }
