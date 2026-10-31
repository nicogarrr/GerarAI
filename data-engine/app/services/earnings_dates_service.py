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
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models.entities import Company, DividendRecord, EarningsDate, Position, WatchItem
from app.services.async_bridge import run_from_any_context
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
        select(Company)
        .join(Position, Position.company_id == Company.id)
        .where(Position.quantity > 0, *tenant_filters(db, Position))
    ).all()
    watched = db.scalars(
        select(Company)
        .join(WatchItem, WatchItem.symbol == Company.ticker)
        .where(*tenant_filters(db, WatchItem))
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for company in watched:
        if company.ticker:
            out[str(company.ticker).upper()] = {"company": company, "origin": "watchlist"}
    for company in held:  # la cartera gana el origen
        if company.ticker:
            out[str(company.ticker).upper()] = {"company": company, "origin": "cartera"}
    return out


# Zona horaria del mercado por sufijo Yahoo. Yahoo da la fecha como instante UTC:
# una publicacion el 5-nov en Tokio (00:00 JST) cae el 4-nov en UTC y mostraria el
# dia equivocado. Sin sufijo = linea US. Sufijo desconocido = sin fecha (nunca el
# dia UTC a ciegas).
_SUFFIX_TZ = {
    "": "America/New_York", "TO": "America/Toronto", "V": "America/Toronto",
    "L": "Europe/London", "IL": "Europe/London", "MC": "Europe/Madrid", "PA": "Europe/Paris",
    "DE": "Europe/Berlin", "F": "Europe/Berlin", "AS": "Europe/Amsterdam", "BR": "Europe/Brussels",
    "MI": "Europe/Rome", "LS": "Europe/Lisbon", "SW": "Europe/Zurich", "VI": "Europe/Vienna",
    "ST": "Europe/Stockholm", "CO": "Europe/Copenhagen", "HE": "Europe/Helsinki", "OL": "Europe/Oslo",
    "T": "Asia/Tokyo", "HK": "Asia/Hong_Kong", "SS": "Asia/Shanghai", "SZ": "Asia/Shanghai",
    "KS": "Asia/Seoul", "KQ": "Asia/Seoul", "TW": "Asia/Taipei", "TWO": "Asia/Taipei",
    "SI": "Asia/Singapore", "NS": "Asia/Kolkata", "BO": "Asia/Kolkata", "AX": "Australia/Sydney",
    "NZ": "Pacific/Auckland", "SA": "America/Sao_Paulo", "MX": "America/Mexico_City",
    "TA": "Asia/Jerusalem", "JO": "Africa/Johannesburg",
}


def market_timezone(symbol: str) -> str | None:
    """Zona del mercado del simbolo Yahoo, o None si no se puede asegurar."""
    head, _, suffix = symbol.strip().upper().partition(".")
    if not head:
        return None
    if suffix in {"A", "B", "C"}:  # clases de acciones US (BRK.B), no una bolsa
        return _SUFFIX_TZ[""]
    return _SUFFIX_TZ.get(suffix)


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
    try:
        for ticker, symbol in symbols.items():
            try:
                response = client.get(
                    f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
                    params={"modules": "calendarEvents", "crumb": crumb},
                )
                payload = response.json()["quoteSummary"]["result"]
                earnings = payload[0]["calendarEvents"]["earnings"] if payload else {}
                dates = earnings.get("earningsDate") or []
                zone = market_timezone(symbol)
                if dates and zone is None:
                    logger.info("earnings_dates yahoo %s: zona horaria desconocida, sin fecha", symbol)
                elif dates:
                    raw = min(int(item["raw"]) for item in dates if item.get("raw"))
                    result[ticker] = {
                        "date": datetime.fromtimestamp(raw, ZoneInfo(zone)).date(),
                        "estimate": bool(earnings.get("isEarningsDateEstimate")),
                    }
            except Exception as exc:  # noqa: BLE001
                logger.info("earnings_dates yahoo %s: %s", symbol, exc)
            time.sleep(YAHOO_PAUSE_S)
    finally:
        client.close()
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
    return run_from_any_context(_nasdaq_scan(tickers, today))


def merge_candidate(yahoo: dict | None, nasdaq: dict | None) -> dict[str, Any] | None:
    """Una fila por ticker segun las reglas del modulo; None si ninguna fuente tiene fecha."""
    if yahoo and nasdaq and yahoo["date"] == nasdaq["date"]:
        return {
            "date": yahoo["date"], "session": nasdaq["session"], "fiscal": nasdaq["fiscal"],
            "confirmed": not yahoo["estimate"], "source": "nasdaq+yahoo",
            "label": f"{SOURCE_NASDAQ_LABEL} + {SOURCE_YAHOO_LABEL}",
        }
    if yahoo:
        # Yahoo y NASDAQ discrepan: al menos una de las dos esta proyectando
        # (medido 19 oct 2026: NVDA 17-nov Yahoo vs 18-nov NASDAQ; AVGO 9-dic
        # vs 10-dic, ambas con ``isEarningsDateEstimate=False``). Una fecha
        # contradicha por la otra fuente NO puede exhibirse como confirmada,
        # aunque Yahoo la marque como no estimada. Se conserva la fecha de
        # Yahoo (regla del modulo) pero se degrada el sello a no confirmada.
        disagreed = nasdaq is not None and nasdaq["date"] != yahoo["date"]
        return {
            "date": yahoo["date"], "session": None, "fiscal": None,
            "confirmed": False if disagreed else not yahoo["estimate"],
            "source": "yahoo",
            "label": (
                f"{SOURCE_YAHOO_LABEL} (NASDAQ publica otra fecha: sin confirmar)"
                if disagreed else SOURCE_YAHOO_LABEL
            ),
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
    try:
        yahoo = yahoo_fetcher(yahoo_symbols) if yahoo_symbols else {}
    except Exception as exc:  # noqa: BLE001 - una fuente caida nunca tira la otra
        logger.warning("earnings_dates: yahoo fallo por completo: %s", exc)
        yahoo = {}
    try:
        nasdaq = nasdaq_fetcher(us, today) if us else {}
    except Exception as exc:  # noqa: BLE001 - idem NASDAQ
        logger.warning("earnings_dates: nasdaq fallo por completo: %s", exc)
        nasdaq = {}
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
        if candidate["date"] < today:
            # El proveedor aun ensena la fecha ya celebrada (ventana tipica
            # tras publicar, hasta que programa la siguiente). No es la
            # proxima: NUNCA se borran las filas futuras vigentes ni se
            # inserta un duplicado. Antes de este guard el insert chocaba con
            # uq_earnings_date_ticker_day_source, el commit de TODA la corrida
            # reventaba y ningun ticker se renovaba (repro 22 oct 2026:
            # tests/test_earnings_dates_refresh_repro.py).
            future_row = db.scalar(
                select(EarningsDate.id).where(
                    EarningsDate.ticker == ticker, EarningsDate.source != "manual",
                    EarningsDate.event_date >= today,
                )
            )
            if future_row is None and not manual:
                missing.append(ticker)
            existing = db.scalar(
                select(EarningsDate).where(
                    EarningsDate.ticker == ticker,
                    EarningsDate.event_date == candidate["date"],
                    EarningsDate.source == candidate["source"],
                )
            )
            if existing is not None:
                # El proveedor confirma que sigue mostrando esa fecha: se
                # renueva fetched_at (is_fresh la usa en la watchlist).
                existing.fetched_at = datetime.now(UTC)
            else:
                db.add(
                    EarningsDate(
                        ticker=ticker, event_date=candidate["date"], session=candidate["session"],
                        fiscal_label=candidate["fiscal"], confirmed=candidate["confirmed"],
                        source=candidate["source"], source_label=candidate["label"],
                        fetched_at=datetime.now(UTC),
                    )
                )
                written += 1
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


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# Una fecha automatica que el refresco lleva dias sin renovar ya no es fiable
# (el proveedor pudo moverla): se omite y el ticker aparece como "sin fecha".
STALE_AFTER = timedelta(days=3)


def is_fresh(row: EarningsDate, now: datetime | None = None) -> bool:
    """Manual no caduca; una fila automatica sin renovar en STALE_AFTER si."""
    return row.source == "manual" or _aware(row.fetched_at) >= (now or datetime.now(UTC)) - STALE_AFTER


def _keep_auto_row(row: EarningsDate, today: date, cutoff: datetime) -> bool:
    """Fila automatica vigente: futura y renovada; o ya ocurrida y confirmada por la fuente.

    El refresco solo toca fechas >= hoy, asi que una fila pasada deja de renovarse y
    caducaria a los 3 dias aunque el hecho (resultados ya publicados) no cambie. Una
    fecha pasada solo es historia si la fuente la daba confirmada (``True``): una fecha
    estimada o sin dato puede no haber ocurrido nunca ese dia (fantasma) y no se muestra
    como "publicado".
    """
    if row.event_date < today:
        return row.confirmed is True
    return _aware(row.fetched_at) >= cutoff


def followed_calendar(
    db: Session, desde: date, hasta: date, *, now: datetime | None = None, scope: str = "followed"
) -> dict[str, Any]:
    followed = followed_companies(db)
    if scope == "watchlist":
        followed = {t: v for t, v in followed.items() if v["origin"] == "watchlist"}
    cutoff = (now or datetime.now(UTC)) - STALE_AFTER
    today = (now or datetime.now(UTC)).date()
    all_rows = db.scalars(
        select(EarningsDate)
        .where(EarningsDate.ticker.in_(list(followed) or [""]),
               EarningsDate.event_date >= desde, EarningsDate.event_date <= hasta)
        .order_by(EarningsDate.event_date, EarningsDate.ticker)
    ).all()
    rows = [row for row in all_rows if row.source == "manual" or _keep_auto_row(row, today, cutoff)]
    # Fechas futuras que existen pero caducaron sin renovarse: no es "sin publicar", es "sin dato reciente".
    stale_future = {
        r.ticker for r in all_rows
        if r.event_date >= today and not (r.source == "manual" or _keep_auto_row(r, today, cutoff))
    }
    # Si hay fila manual y automatica el mismo ticker, la manual (empresa) gana.
    by_ticker: dict[str, list[EarningsDate]] = {}
    for row in rows:
        by_ticker.setdefault(row.ticker, []).append(row)
    events: list[dict[str, Any]] = []
    covered: set[str] = set()
    for ticker, group in by_ticker.items():
        company = followed[ticker]["company"]
        upcoming = [r for r in group if r.event_date >= today]
        past = [r for r in group if r.event_date < today]
        # Futuro: la manual (empresa) gana, si no la mas proxima. Historia: solo la ultima ya ocurrida;
        # nunca mezclar ambas, o la proxima fecha desapareceria detras de la antigua.
        chosen_rows: list[EarningsDate] = []
        if upcoming:
            chosen_rows.append(next((r for r in upcoming if r.source == "manual"), upcoming[0]))
            covered.add(ticker)
        if past:
            latest = max(r.event_date for r in past)
            same_day = [r for r in past if r.event_date == latest]
            chosen_rows.append(next((r for r in same_day if r.source == "manual"), same_day[0]))
        for chosen in chosen_rows:
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
    # "Sin fecha" = sin proxima fecha: tener solo historia no cuenta como cobertura.
    return {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "followed_count": len(followed), "count": len(events),
        "days": [{"date": d, "events": evs} for d, evs in days.items()],
        "without_date_in_range": sorted(set(followed) - covered),
        # Subconjunto de lo anterior: tenia fecha futura, pero el dato no se renueva desde hace mas de STALE_AFTER.
        "stale_date_in_range": sorted((set(followed) - covered) & stale_future),
    }



def portfolio_dividend_dates(db: Session, desde: date, hasta: date) -> list[dict[str, Any]]:
    """Ex-dividendo y pago de las posiciones abiertas (tabla ``dividend_records``, sin proveedores).

    Son fechas publicadas por la fuente que ya se guardó: «oficial». Sin fila no hay fecha.
    """
    held = {t: v for t, v in followed_companies(db).items() if v["origin"] == "cartera"}
    if not held:
        return []
    by_id = {v["company"].id: (t, v["company"]) for t, v in held.items()}
    rows = db.scalars(select(DividendRecord).where(DividendRecord.company_id.in_(list(by_id)))).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        ticker, company = by_id[row.company_id]
        amount = float(row.amount) if row.amount is not None else None
        detail = f"{amount:g} {row.currency} por acción" if amount else None
        for kind, day in (("ex_dividend", row.ex_date), ("dividend_payment", row.pay_date)):
            if day is None or not (desde <= day <= hasta):
                continue
            items.append({
                "date": day.isoformat(), "ticker": ticker, "company": company.name, "kind": kind,
                "status": "oficial", "detail": detail, "source": row.source, "source_url": None,
            })
    return items


UPCOMING_LIMITATIONS = [
    "Juntas de accionistas: no hay una fuente gratuita guardada; no se muestran fechas inventadas.",
]


def portfolio_upcoming(db: Session, desde: date, hasta: date, *, now: datetime | None = None) -> dict[str, Any]:
    """«Próximas fechas» de toda la cartera: resultados (oficial o estimada), ex-dividendo y pago.

    Reutiliza el calendario de seguidas (``earnings_dates``) y los dividendos guardados; cada
    fecha lleva su recordatorio (el día antes), el mismo que pone el calendario suscrito.
    """
    items: list[dict[str, Any]] = []
    calendar = followed_calendar(db, desde, hasta, now=now)
    for day in calendar["days"]:
        for event in day["events"]:
            if event["origin"] != "cartera" or event["date"] < desde.isoformat():
                continue
            items.append({
                "date": event["date"], "ticker": event["ticker"], "company": event["company"], "kind": "results",
                "status": "oficial" if event["confirmed"] is True else "estimada",
                "detail": event.get("fiscal_label"), "source": event["source"], "source_url": event["source_url"],
            })
    items += portfolio_dividend_dates(db, desde, hasta)
    for item in items:
        item["reminder"] = (date.fromisoformat(item["date"]) - timedelta(days=1)).isoformat()
    items.sort(key=lambda i: (i["date"], i["ticker"], i["kind"]))
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "count": len(items), "items": items,
            "limitations": UPCOMING_LIMITATIONS}
