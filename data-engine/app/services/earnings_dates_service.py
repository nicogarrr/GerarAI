"""Proximas fechas de resultados de cartera + watchlist (fuentes gratuitas).

Fuentes, ambas publicas y sin clave:

* Yahoo Finance ``quoteSummary?modules=calendarEvents``: fecha y la marca
  ``isEarningsDateEstimate`` (confirmada vs estimada). Cubre tambien bolsas
  no US (``.L``, ``.MC``...), si el proveedor la tiene.
* Calendario publico de NASDAQ (``api.nasdaq.com/api/calendar/earnings``), dia
  a dia: aporta la franja (antes de apertura / tras cierre) y el trimestre
  cerrado. Solo lineas US.

Reglas de veracidad: nunca se inventa una hora (solo la franja que publica
NASDAQ); si ambas fuentes discrepan en la fecha manda Yahoo (lleva la marca de
estimada) y la franja de NASDAQ se descarta; si ninguna responde, el ticker
queda sin fecha, no con una supuesta. Las filas ``source='manual'`` (fecha
anunciada por la empresa y enlazada) no las toca el refresco automatico.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import Company, EarningsDate, Position, WatchItem
from app.services.connectors.earnings_calendar import BROWSER_HEADERS, EARNINGS_URL
from app.services.market_refresh_service import _us_listed
from app.services.propicks_price_service import yahoo_symbol

logger = logging.getLogger(__name__)

SOURCE_YAHOO_LABEL = "Yahoo Finance (calendarEvents)"
SOURCE_NASDAQ_LABEL = "Calendario público de NASDAQ"
SESSION_BY_NASDAQ = {
    "time-pre-market": "pre_market",
    "before-market": "pre_market",
    "time-after-hours": "after_market",
    "after-market": "after_market",
}
NASDAQ_HORIZON_DAYS = 75
YAHOO_PAUSE_S = 0.25


def followed_companies(db: Session) -> dict[str, dict[str, Any]]:
    """ticker -> {company, origin} de cartera (posicion abierta) y watchlist del tenant."""
    held = db.scalars(
        select(Company).join(Position, Position.company_id == Company.id).where(Position.quantity > 0)
    ).all()
    watched = db.scalars(select(Company).join(WatchItem, WatchItem.symbol == Company.ticker)).all()
    out: dict[str, dict[str, Any]] = {}
    for company in watched:
        if company.ticker:
            out[str(company.ticker).upper()] = {"company": company, "origin": "watchlist"}
    for company in held:  # la cartera gana el origen
        if company.ticker:
            out[str(company.ticker).upper()] = {"company": company, "origin": "cartera"}
    return out


def _yahoo_session() -> tuple[httpx.Client, str]:
    client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)
    client.get("https://fc.yahoo.com")  # 404 esperado: solo fija la cookie
    crumb = client.get("https://query1.finance.yahoo.com/v1/test/getcrumb").text.strip()
    if not crumb or " " in crumb or len(crumb) > 40:
        raise RuntimeError("yahoo_crumb_unavailable")
    return client, crumb


def fetch_yahoo_dates(symbols: dict[str, str]) -> dict[str, dict[str, Any]]:
    """ticker -> {date, estimate} para los simbolos Yahoo dados. Fallos = ausencia."""
    result: dict[str, dict[str, Any]] = {}
    try:
        client, crumb = _yahoo_session()
    except Exception as exc:  # noqa: BLE001
        logger.warning("earnings_dates yahoo crumb: %s", exc)
        return result
    with client:
        for ticker, symbol in symbols.items():
            try:
                response = client.get(
                    f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
                    params={"modules": "calendarEvents", "crumb": crumb},
                )
                payload = response.json()["quoteSummary"]["result"]
                earnings = payload[0]["calendarEvents"]["earnings"] if payload else {}
                dates = earnings.get("earningsDate") or []
                if dates:
                    raw = min(int(item["raw"]) for item in dates if item.get("raw"))
                    result[ticker] = {
                        "date": datetime.fromtimestamp(raw, UTC).date(),
                        "estimate": bool(earnings.get("isEarningsDateEstimate")),
                    }
            except Exception as exc:  # noqa: BLE001
                logger.info("earnings_dates yahoo %s: %s", symbol, exc)
            time.sleep(YAHOO_PAUSE_S)
    return result


async def _nasdaq_day(client: httpx.AsyncClient, day: date, sem: asyncio.Semaphore) -> list[dict]:
    async with sem:
        for _ in range(2):
            try:
                response = await client.get(EARNINGS_URL, params={"date": day.isoformat()}, timeout=20)
                return list((response.json().get("data") or {}).get("rows") or [])
            except Exception as exc:  # noqa: BLE001
                logger.info("earnings_dates nasdaq %s: %s", day, exc)
    return []


async def _nasdaq_scan(tickers: set[str], today: date) -> dict[str, dict[str, Any]]:
    sem = asyncio.Semaphore(4)
    days = [today + timedelta(days=i) for i in range(NASDAQ_HORIZON_DAYS)]
    days = [d for d in days if d.weekday() < 5]
    async with httpx.AsyncClient(headers=BROWSER_HEADERS) as client:
        rows_by_day = await asyncio.gather(*[_nasdaq_day(client, d, sem) for d in days])
    found: dict[str, dict[str, Any]] = {}
    for day, rows in zip(days, rows_by_day, strict=True):
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            if symbol in tickers and symbol not in found:  # la primera fecha futura
                found[symbol] = {
                    "date": day,
                    "session": SESSION_BY_NASDAQ.get(str(row.get("time") or "")),
                    "fiscal": str(row.get("fiscalQuarterEnding") or "") or None,
                }
    return found


def fetch_nasdaq_dates(tickers: set[str], today: date) -> dict[str, dict[str, Any]]:
    if not tickers:
        return {}
    return asyncio.run(_nasdaq_scan(tickers, today))


def merge_candidate(yahoo: dict | None, nasdaq: dict | None) -> dict[str, Any] | None:
    """Una fila por ticker segun las reglas del modulo; None si ninguna fuente tiene fecha."""
    if yahoo and nasdaq and yahoo["date"] == nasdaq["date"]:
        return {
            "date": yahoo["date"], "session": nasdaq["session"], "fiscal": nasdaq["fiscal"],
            "confirmed": not yahoo["estimate"], "source": "nasdaq+yahoo",
            "label": f"{SOURCE_NASDAQ_LABEL} + {SOURCE_YAHOO_LABEL}",
        }
    if yahoo:
        return {
            "date": yahoo["date"], "session": None, "fiscal": None,
            "confirmed": not yahoo["estimate"], "source": "yahoo", "label": SOURCE_YAHOO_LABEL,
        }
    if nasdaq:
        return {
            "date": nasdaq["date"], "session": nasdaq["session"], "fiscal": nasdaq["fiscal"],
            "confirmed": None, "source": "nasdaq", "label": SOURCE_NASDAQ_LABEL,
        }
    return None


def refresh_earnings_dates(
    db: Session,
    *,
    today: date | None = None,
    yahoo_fetcher: Callable[[dict[str, str]], dict] = fetch_yahoo_dates,
    nasdaq_fetcher: Callable[[set[str], date], dict] = fetch_nasdaq_dates,
) -> dict[str, Any]:
    today = today or datetime.now(UTC).date()
    followed = followed_companies(db)
    yahoo_symbols: dict[str, str] = {}
    us: set[str] = set()
    skipped: list[str] = []
    for ticker, info in followed.items():
        company = info["company"]
        symbol = yahoo_symbol(company)
        if symbol:
            yahoo_symbols[ticker] = symbol
        else:
            skipped.append(ticker)
        if _us_listed(company):
            us.add(ticker)
    yahoo = yahoo_fetcher(yahoo_symbols) if yahoo_symbols else {}
    nasdaq = nasdaq_fetcher(us, today) if us else {}
    written, missing, disagree = 0, [], 0
    for ticker in followed:
        manual = db.scalar(
            select(EarningsDate.id).where(
                EarningsDate.ticker == ticker, EarningsDate.source == "manual",
                EarningsDate.event_date >= today,
            )
        )
        candidate = merge_candidate(yahoo.get(ticker), nasdaq.get(ticker))
        if yahoo.get(ticker) and nasdaq.get(ticker) and yahoo[ticker]["date"] != nasdaq[ticker]["date"]:
            disagree += 1
        if candidate is None:
            if not manual:
                missing.append(ticker)
            continue
        db.execute(
            delete(EarningsDate).where(
                EarningsDate.ticker == ticker, EarningsDate.source != "manual",
                EarningsDate.event_date >= today,
            )
        )
        db.add(
            EarningsDate(
                ticker=ticker, event_date=candidate["date"], session=candidate["session"],
                fiscal_label=candidate["fiscal"], confirmed=candidate["confirmed"],
                source=candidate["source"], source_label=candidate["label"],
                fetched_at=datetime.now(UTC),
            )
        )
        written += 1
    db.commit()
    return {
        "followed": len(followed), "written": written, "without_date": sorted(missing),
        "without_yahoo_symbol": sorted(skipped), "date_disagreements": disagree,
    }


def followed_calendar(db: Session, desde: date, hasta: date) -> dict[str, Any]:
    followed = followed_companies(db)
    rows = db.scalars(
        select(EarningsDate)
        .where(EarningsDate.ticker.in_(list(followed) or [""]),
               EarningsDate.event_date >= desde, EarningsDate.event_date <= hasta)
        .order_by(EarningsDate.event_date, EarningsDate.ticker)
    ).all()
    # Si hay fila manual y automatica el mismo ticker, la manual (empresa) gana.
    by_ticker: dict[str, list[EarningsDate]] = {}
    for row in rows:
        by_ticker.setdefault(row.ticker, []).append(row)
    events: list[dict[str, Any]] = []
    for ticker, group in by_ticker.items():
        chosen = next((r for r in group if r.source == "manual"), group[0])
        company = followed[ticker]["company"]
        events.append({
            "ticker": ticker,
            "company": company.name,
            "origin": followed[ticker]["origin"],
            "date": chosen.event_date.isoformat(),
            "session": chosen.session,
            "fiscal_label": chosen.fiscal_label,
            "confirmed": chosen.confirmed,
            "source": chosen.source_label,
            "source_url": chosen.source_url,
        })
    events.sort(key=lambda e: (e["date"], e["ticker"]))
    days: dict[str, list[dict]] = {}
    for event in events:
        days.setdefault(event["date"], []).append(event)
    covered = {e["ticker"] for e in events}
    return {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "followed_count": len(followed), "count": len(events),
        "days": [{"date": d, "events": evs} for d, evs in days.items()],
        "without_date_in_range": sorted(set(followed) - covered),
    }
