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

SOURCE_NAME = "yahoo_quoteSummary"
PARSER_VERSION = "yahoo-ca-1"
FORM = "CA-INSIDER"
SEDI_URL = "https://www.sedi.ca"
TIMEOUT_SECONDS = 15
PAUSE_SECONDS = 3.0
QUOTESUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary"

# Nuestros tickers canadienses cubiertos -> simbolo Yahoo (mismo hoy).
CA_TICKERS: dict[str, str] = {"BN": "BN", "KRKNF": "KRKNF"}

_BUY_HINTS = ("acquisition", "purchase", "buy")
_SELL_HINTS = ("sale", "disposition", "sell")
# Flujos mecanicos: no son senal (mismo criterio fail-closed que PDMR UK).
_NEUTRAL_HINTS = (
    "exercise", "option", "award", "grant", "vest", "dividend", "drip",
    "subscription", "plan", "gift", "transfer", "conversion",
)


def yahoo_session(client: httpx.Client | None = None) -> tuple[httpx.Client, str]:
    """Cookie fc.yahoo.com + crumb (mismo patron que earnings_dates_service)."""
    owned = client or httpx.Client(
        headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT_SECONDS, follow_redirects=True
    )
    owned.get("https://fc.yahoo.com")  # 404 esperado: solo fija la cookie
    crumb = owned.get("https://query1.finance.yahoo.com/v1/test/getcrumb").text.strip()
    if not crumb or " " in crumb or len(crumb) > 40:
        raise RuntimeError("yahoo_crumb_unavailable")
    return owned, crumb


def fetch_insider_transactions(
    symbol: str, client: httpx.Client, crumb: str
) -> list[dict[str, Any]]:
    """Movimientos crudos de Yahoo para un simbolo; [] si no hay modulo."""
    response = client.get(
        f"{QUOTESUMMARY_URL}/{symbol}",
        params={"modules": "insiderTransactions", "crumb": crumb},
    )
    response.raise_for_status()
    payload = response.json()
    result = (payload.get("quoteSummary") or {}).get("result") or []
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
        "source_url": SEDI_URL,
    }
