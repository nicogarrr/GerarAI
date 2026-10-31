"""Backfill de ``market_prices.quote_currency`` desde la META de Yahoo.

Por que hay NULLs: la columna nacio en la migracion 0087 (2026-10-30) y, por
decision registrada en la propia migracion, no se relleno adivinando: cada
fila anterior quedo NULL, y los spots de Finnhub que no traen unidad
verificable siguen naciendo NULL (``thesis_evidence_service``). La unidad
NUNCA se infiere (ni USD a ciegas ni por magnitud del precio): se pide a la
chart API de Yahoo, que publica ``meta.currency`` por simbolo.

Contrato:
* Una llamada a Yahoo por empresa (no por fila), con pausa entre llamadas
  para respetar el pacing del proveedor.
* Idempotente: solo toca filas con ``quote_currency IS NULL``; una segunda
  pasada actualiza 0 filas.
* ``dry_run``: cuenta lo que haria y no escribe nada (rollback).
* Si Yahoo no da divisa para un ticker, las filas quedan NULL (honesto) y la
  empresa aparece en ``unresolved``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice

FetchCurrency = Callable[[str], Awaitable[str | None]]
Sleep = Callable[[float], Awaitable[None]]

_MAX_UNIT_LEN = 12  # columna String(12): "USD", "GBp", "EUR"...


def _clean_unit(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    unit = value.strip()
    if not unit or len(unit) > _MAX_UNIT_LEN or not unit.isprintable():
        return None
    return unit


def _companies_with_null_units(
    db: Session, *, tickers: list[str] | None, limit: int | None
) -> list[tuple[int, str, int]]:
    """(company_id, ticker, filas NULL) ordenado por id: pasada determinista."""
    stmt = (
        select(MarketPrice.company_id, Company.ticker, func.count())
        .join(Company, Company.id == MarketPrice.company_id)
        .where(MarketPrice.quote_currency.is_(None))
        .group_by(MarketPrice.company_id, Company.ticker)
        .order_by(MarketPrice.company_id)
    )
    if tickers:
        stmt = stmt.where(Company.ticker.in_(tickers))
    if limit is not None:
        stmt = stmt.limit(limit)
    return [(int(cid), str(t), int(n)) for cid, t, n in db.execute(stmt).all()]


async def backfill_quote_currency(
    db: Session,
    *,
    fetch_currency: FetchCurrency,
    dry_run: bool = False,
    pause_seconds: float = 1.0,
    company_limit: int | None = None,
    tickers: list[str] | None = None,
    sleep: Sleep = asyncio.sleep,
) -> dict:
    """Rellena unidades NULL con la divisa REAL del proveedor. Resumen dict."""
    targets = _companies_with_null_units(db, tickers=tickers, limit=company_limit)
    result: dict = {
        "dry_run": dry_run,
        "companies_scanned": len(targets),
        "companies_updated": 0,
        "rows_updated": 0,
        "unresolved": [],
        "per_company": [],
    }
    first = True
    for company_id, ticker, null_rows in targets:
        if not first and pause_seconds > 0:
            await sleep(pause_seconds)  # pacing del proveedor: 1 llamada/empresa
        first = False
        try:
            unit = _clean_unit(await fetch_currency(ticker))
        except Exception as exc:  # red/rate-limit: fuera, se reintenta en otra pasada
            result["unresolved"].append({"ticker": ticker, "reason": f"fetch_error: {type(exc).__name__}"})
            continue
        if unit is None:
            result["unresolved"].append({"ticker": ticker, "reason": "provider_without_currency"})
            continue
        updated = 0
        if not dry_run:
            updated = int(
                db.execute(
                    update(MarketPrice)
                    .where(MarketPrice.company_id == company_id, MarketPrice.quote_currency.is_(None))
                    .values(quote_currency=unit)
                ).rowcount
            )
        else:
            updated = null_rows
        result["companies_updated"] += 1
        result["rows_updated"] += updated
        result["per_company"].append({"ticker": ticker, "currency": unit, "rows": updated})
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return result
