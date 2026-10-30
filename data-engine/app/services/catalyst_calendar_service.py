"""Calendario unico de catalizadores de la cartera.

Une, para las empresas con posicion abierta (quantity > 0), tres fuentes que
hasta ahora vivian en pantallas distintas:

* resultados (earnings) del calendario publico de NASDAQ,
* fecha ex-dividendo del mismo calendario,
* acciones corporativas registradas en GerarAI (splits, etc.) aun no aplicadas.

A eso se suman dos fuentes ingeridas:

* fecha de PAGO de dividendo, de los ``DividendRecord`` ya ingeridos
  (posiciones y watchlist, cualquier mercado): solo registros cuya fuente
  trae fecha de pago; si la fuente no la trae (p. ej. Yahoo chart), no hay
  evento de pago y nada se estima;
* fecha ex-dividendo de posiciones y watchlist FUERA de bolsa US, desde los
  mismos registros ingeridos (NASDAQ no las cubre).

Cobertura declarada: el calendario de dividendos de NASDAQ se consulta por dia
y solo devuelve las filas cuya fecha ex-dividendo cae en ese dia. Cuando la
fila trae fecha de pago se muestra en el detalle del evento ex, aunque caiga
fuera del rango. Resultados y dividendos de NASDAQ se cruzan solo con
posiciones y watchlist en bolsa US y USD (misma regla que
``market_refresh_service._us_listed``): un ticker pelado de un emisor no-US
puede coincidir con otro emisor.

Honestidad de datos: solo se emiten eventos que la fuente trae; nada se
estima ni se inventa. Si NASDAQ no responde, el estado lo dice y las acciones
corporativas propias siguen apareciendo. ``source`` nombra el origen de cada
evento.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models.entities import Company, CorporateAction, Position
from app.services.date_format import format_date_es
from app.services.market_refresh_service import _us_listed

SOURCE_NASDAQ = "Calendario público de NASDAQ"
SOURCE_GERARAI = "Acción corporativa registrada en GerarAI"

SOURCE_SEC_RULE = "Regla SEC (Form 10-Q/10-K) aplicada al último informe en EDGAR"

# Historial de dividendos ya ingerido (DividendRecord): la etiqueta nombra el
# proveedor del registro, nunca una fuente generica.
_RECORD_SOURCE_LABEL = {
    "yahoo_finance": "Historial de dividendos ingerido de Yahoo Finance",
    "fmp": "Historial de dividendos ingerido de FMP",
}


def record_source_label(source: str) -> str:
    """Etiqueta de fuente para eventos sacados de ``DividendRecord``."""
    return _RECORD_SOURCE_LABEL.get(source, f"Historial de dividendos ingerido ({source})")

logger = logging.getLogger(__name__)

_TYPE_ORDER = {
    "earnings": 0,
    "dividend_ex": 1,
    "dividend_payment": 2,
    "filing_deadline": 3,
    "corporate_action": 4,
}

# Valores reales de ``time`` del calendario NASDAQ (medidos), mas los alias antiguos.
_TIME_LABEL = {
    "time-pre-market": "antes de la apertura",
    "time-after-hours": "tras el cierre",
    "before-market": "antes de la apertura",
    "after-market": "tras el cierre",
}


# Plazos de presentacion (dias tras el cierre del periodo), Form 10-Q / 10-K:
# large accelerated 40/60, accelerated 40/75, resto 45/90.
# Categorías de filer de la SEC traducidas; una categoría desconocida se
# muestra tal cual (nunca se inventa la traducción).
_FILER_CATEGORY_ES = {
    "large accelerated filer": "emisor acelerado grande",
    "accelerated filer": "emisor acelerado",
    "non-accelerated filer": "emisor no acelerado",
    "smaller reporting company": "empresa de información reducida",
}

_FILER_DEADLINES = {
    "large accelerated filer": (40, 60),
    "accelerated filer": (40, 75),
    "non-accelerated filer": (45, 90),
}
_MAX_DEADLINES = (45, 90)
_PERIODIC = {"10-Q", "10-K"}


def _add_months(day: date, months: int) -> date:
    """Suma meses de calendario; si `day` era fin de mes, devuelve el fin de mes destino."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    was_month_end = day.day == calendar.monthrange(day.year, day.month)[1]
    return date(year, month, last if was_month_end else min(day.day, last))


def _next_business_day(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _is_month_end(day: date) -> bool:
    return day.day == calendar.monthrange(day.year, day.month)[1]


def _next_period_end(periods: list[date]) -> tuple[date, bool] | None:
    """(siguiente cierre estimado, es_aproximado) a partir de los cierres ya presentados.

    Cierre en fin de mes: +3 meses de calendario (exacto). Emisores de 52/53
    semanas (cierre no en fin de mes, trimestres de 12/13/16 semanas): se toma el
    informe del ejercicio anterior (cierre mas cercano a ultimo-364 dias), el
    siguiente a ese, y se le suman 364 dias. Asi se respeta la longitud real de
    cada trimestre; queda un error de hasta ~1 semana en ejercicios de 53
    semanas. Sin ese historial no se estima nada (None)."""
    last = periods[-1]
    if _is_month_end(last):
        return _add_months(last, 3), False
    target = last - timedelta(days=364)
    prior = min(periods, key=lambda d: abs((d - target).days))
    if abs((prior - target).days) > 10:
        return None
    following = [d for d in periods if d > prior + timedelta(days=30)]
    if not following or following[0] >= last:
        return None
    return following[0] + timedelta(days=364), True


def _near_fiscal_year_end(day: date, fy_month: int, fy_day: int) -> bool:
    """True si `day` esta a +-10 dias del fin de ejercicio (fiscalYearEnd MMDD)."""
    for year in (day.year - 1, day.year, day.year + 1):
        last = calendar.monthrange(year, fy_month)[1]
        if abs((date(year, fy_month, min(fy_day, last)) - day).days) <= 10:
            return True
    return False


def filing_deadline_event(submissions: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    """Proximo plazo de 10-Q/10-K de un emisor, INFERIDO por regla SEC. Funcion pura.

    Base: cierres de periodo (``reportDate``) de los 10-Q/10-K ya presentados en
    EDGAR; el siguiente cierre se estima como en `_next_period_end`. Es 10-K si
    ese cierre cae a +-10 dias del fin de ejercicio (``fiscalYearEnd``), si no
    10-Q. El plazo depende de la categoria de filer de EDGAR; sin ella se usa el
    MAXIMO de la regla y se dice. Plazo en sabado/domingo pasa al lunes; los
    festivos no se modelan. Sin historial suficiente o sin fiscalYearEnd, None:
    no se inventa nada.
    """
    recent = (submissions.get("filings") or {}).get("recent") or {}
    periods_set: set[date] = set()
    for form, report in zip(recent.get("form") or [], recent.get("reportDate") or [], strict=False):
        if form not in _PERIODIC:
            continue
        period = _parse_us_date(report)
        if period is not None:
            periods_set.add(period)
    if not periods_set:
        return None
    periods = sorted(periods_set)
    fy_end = str(submissions.get("fiscalYearEnd") or "")
    if len(fy_end) != 4 or not fy_end.isdigit() or not 1 <= int(fy_end[:2]) <= 12 or not 1 <= int(fy_end[2:]) <= 31:
        return None
    estimate = _next_period_end(periods)
    if estimate is None:
        return None
    next_period, approx = estimate
    form = "10-K" if _near_fiscal_year_end(next_period, int(fy_end[:2]), int(fy_end[2:])) else "10-Q"
    category = str(submissions.get("category") or "").strip().lower()
    days_q_k = _FILER_DEADLINES.get(category)
    days = (days_q_k or _MAX_DEADLINES)[1 if form == "10-K" else 0]
    deadline = _next_business_day(next_period + timedelta(days=days))
    basis = (
        f"{days} días tras el cierre de periodo estimado ({format_date_es(next_period)}) "
        f"sobre el último informe periódico (cierre {format_date_es(periods[-1])})"
    )
    if approx:
        basis += "; emisor de 52/53 semanas: fecha aproximada (hasta ~1 semana)"
    if days_q_k is None:
        basis += "; categoría de filer no disponible: se usa el plazo máximo de la regla"
    else:
        basis += f"; categoría EDGAR: {_FILER_CATEGORY_ES.get(category, submissions.get('category'))}"
    return {
        "date": deadline.isoformat(),
        "ticker": ticker.upper(),
        "type": "filing_deadline",
        "title": f"Plazo para presentar el {form}",
        "detail": basis,
        "source": SOURCE_SEC_RULE,
    }


def _default_sec_fetchers() -> tuple[Any, Any]:
    from app.services.connectors.sec import SECClient

    sec = SECClient()
    return sec.cik_for_ticker, sec.submissions


# Tope de emisores consultados por peticion, presupuesto total de tiempo y
# memoria corta de fallos: con la SEC caida o lenta, el calendario devuelve
# parcial marcado en vez de repetir N reintentos en cada carga.
MAX_DEADLINE_TICKERS = 60
DEADLINE_BUDGET_SECONDS = 20.0
DEADLINE_FAILURE_TTL_SECONDS = 120.0
_FAILED_UNTIL: dict[str, float] = {}


async def fetch_filing_deadlines(
    tickers: set[str],
    desde: date,
    hasta: date,
    *,
    cik_fetcher: Callable[[str], Awaitable[str | None]] | None = None,
    submissions_fetcher: Callable[[str], Awaitable[dict[str, Any] | None]] | None = None,
    concurrency: int = 4,
    budget_seconds: float = DEADLINE_BUDGET_SECONDS,
) -> dict[str, Any]:
    """(events, status, errors) de plazos 10-Q/10-K para tickers US con posicion.

    Nunca lanza por red: un emisor sin CIK/submissions cuenta como error visible
    y el resto sigue. ``status``: ok / partial / unavailable (todos fallaron)."""
    if not tickers:
        return {"status": "ok", "events": [], "errors": []}
    default_cik, default_subs = _default_sec_fetchers()  # solo construye el cliente, sin red
    get_cik: Callable[[str], Awaitable[str | None]] = (
        cik_fetcher if cik_fetcher is not None else default_cik
    )
    get_submissions: Callable[[str], Awaitable[dict[str, Any] | None]] = (
        submissions_fetcher if submissions_fetcher is not None else default_subs
    )
    gate = asyncio.Semaphore(concurrency)
    now = time.monotonic()
    ordered = sorted(tickers)
    to_query = [t for t in ordered if _FAILED_UNTIL.get(t, 0.0) <= now][:MAX_DEADLINE_TICKERS]
    skipped_failed = [t for t in ordered if _FAILED_UNTIL.get(t, 0.0) > now]
    skipped_cap = [t for t in ordered if t not in to_query and t not in skipped_failed]

    async def one(ticker: str) -> tuple[str, dict[str, Any] | None, bool]:
        async with gate:
            try:
                cik = await get_cik(ticker)
                if not cik:
                    return ticker, None, True
                data = await get_submissions(cik)
            except Exception as exc:  # noqa: BLE001 - red/4xx/5xx: degradacion visible
                logger.warning("plazos 10-Q/10-K %s: %s", ticker, type(exc).__name__)
                return ticker, None, True
            return ticker, data if isinstance(data, dict) else None, not isinstance(data, dict)

    tasks = {asyncio.ensure_future(one(t)): t for t in to_query}
    done: set[asyncio.Task[tuple[str, dict[str, Any] | None, bool]]] = set()
    if tasks:
        done, pending = await asyncio.wait(tasks, timeout=budget_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    results = [task.result() for task in done if not task.cancelled() and task.exception() is None]
    answered = {r[0] for r in results}
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for ticker in skipped_cap:
        errors.append(f"Plazos 10-Q/10-K: no consultado {ticker} (tope de {MAX_DEADLINE_TICKERS} emisores por petición)")
    for ticker in skipped_failed:
        errors.append(f"Plazos 10-Q/10-K: EDGAR no disponible para {ticker}")
    for ticker in to_query:
        if ticker not in answered:
            _FAILED_UNTIL[ticker] = now + DEADLINE_FAILURE_TTL_SECONDS
            errors.append(f"Plazos 10-Q/10-K: EDGAR no disponible para {ticker}")
    for ticker, data, failed in sorted(results):
        if failed or data is None:
            _FAILED_UNTIL[ticker] = now + DEADLINE_FAILURE_TTL_SECONDS
            errors.append(f"Plazos 10-Q/10-K: EDGAR no disponible para {ticker}")
            continue
        event = filing_deadline_event(data, ticker)
        if event is not None and desde <= date.fromisoformat(event["date"]) <= hasta:
            events.append(event)
    if errors and len(errors) == len(tickers):
        status = "unavailable"
    else:
        status = "partial" if errors else "ok"
    return {"status": status, "events": events, "errors": errors}


def _es_number(value: float, decimals: int) -> str:
    """Numero con coma decimal y signo menos explicito (es-ES)."""
    return f"{value:.{decimals}f}".replace(".", ",")


def watchlist_us_tickers(db: Session, held_us: set[str]) -> set[str]:
    """Tickers US (bolsa US y USD) de la watchlist que NO estan ya en cartera.

    Misma regla ``_us_listed`` que las posiciones: NASDAQ solo se cruza con
    lineas US. La cartera gana el origen: un ticker en ambas se etiqueta
    ``cartera``.
    """
    from app.models import WatchItem

    rows = db.scalars(
        select(Company)
        .join(WatchItem, WatchItem.symbol == Company.ticker)
        .where(*tenant_filters(db, WatchItem))
    ).all()
    return {
        str(c.ticker).upper()
        for c in rows
        if c.ticker and _us_listed(c) and str(c.ticker).upper() not in held_us
    }


def watchlist_tickers(db: Session, held: set[str]) -> set[str]:
    """Tickers de la watchlist (cualquier mercado) que NO estan en cartera.

    Para los dividendos ingeridos no aplica el filtro US de NASDAQ: la fuente
    es el historial propio. La cartera gana el origen igual que en el resto.
    """
    from app.models import WatchItem

    rows = db.scalars(
        select(Company)
        .join(WatchItem, WatchItem.symbol == Company.ticker)
        .where(*tenant_filters(db, WatchItem))
    ).all()
    return {
        str(c.ticker).upper()
        for c in rows
        if c.ticker and str(c.ticker).upper() not in held
    }


def upcoming_dividend_records(
    db: Session, tickers: set[str], desde: date, hasta: date
) -> list[dict[str, Any]]:
    """Dividendos ingeridos (``DividendRecord``) con fecha ex o de pago en rango.

    Solo lo que la fuente declaro: registros sin fecha de pago (Yahoo chart no
    la expone) salen con ``pay_date=None`` y no generan evento de pago. Las
    cantidades de Yahoo vienen ajustadas por splits (lo declara el ingestion
    service); la etiqueta de fuente va en cada fila.
    """
    from app.models import DividendRecord

    if not tickers:
        return []
    rows = db.execute(
        select(DividendRecord, Company.ticker)
        .join(Company, DividendRecord.company_id == Company.id)
        .where(
            Company.ticker.in_(sorted(tickers)),
            *tenant_filters(db, DividendRecord),
            (
                (DividendRecord.ex_date >= desde) & (DividendRecord.ex_date <= hasta)
            )
            | (
                (DividendRecord.pay_date.is_not(None))
                & (DividendRecord.pay_date >= desde)
                & (DividendRecord.pay_date <= hasta)
            ),
        )
    ).all()
    return [
        {
            "ticker": str(ticker).upper(),
            "ex_date": record.ex_date.isoformat() if record.ex_date else None,
            "pay_date": record.pay_date.isoformat() if record.pay_date else None,
            "amount": float(record.amount),
            "currency": record.currency,
            "source": record.source,
        }
        for record, ticker in rows
    ]


def held_tickers(db: Session) -> tuple[set[str], set[str]]:
    """(todos, solo_us): tickers en mayusculas con posicion abierta.

    ``solo_us`` (bolsa US y USD) es el unico conjunto valido para cruzar con
    NASDAQ; ``todos`` sirve para las acciones corporativas propias."""
    companies = db.scalars(
        select(Company)
        .join(Position, Position.company_id == Company.id)
        .where(Position.quantity > 0, *tenant_filters(db, Position))
    ).all()
    todos = {str(c.ticker).upper() for c in companies if c.ticker}
    solo_us = {str(c.ticker).upper() for c in companies if c.ticker and _us_listed(c)}
    return todos, solo_us


def _parse_us_date(value: Any) -> date | None:
    """NASDAQ entrega fechas como ``YYYY-MM-DD`` o ``MM/DD/YYYY``; otra cosa = None."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if "/" in text:
            month, day, year = text.split("/")
            return date(int(year), int(month), int(day))
        return date.fromisoformat(text)
    except ValueError:
        return None


def build_catalysts(
    *,
    held: set[str],
    held_us: set[str],
    desde: date,
    hasta: date,
    earnings: list[dict[str, Any]],
    dividends: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    watchlist_us: set[str] | None = None,
    watchlist: set[str] | None = None,
    records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Filtra a cartera + watchlist, normaliza y ordena.

    ``records`` son los dividendos ingeridos (``upcoming_dividend_records``):
    generan los eventos de fecha de pago (todas las empresas seguidas) y los
    ex-dividendos no-US que NASDAQ no cubre.
    """
    watchlist_us = watchlist_us or set()
    watchlist = watchlist or set()
    records = records or []
    events: list[dict[str, Any]] = []
    for row in earnings:
        ticker = str(row.get("symbol", "")).upper()
        day = _parse_us_date(row.get("date"))
        in_held = ticker in held_us
        if day is None or not desde <= day <= hasta or (not in_held and ticker not in watchlist_us):
            continue
        detail = []
        # Solo franjas conocidas: "time-not-supplied" o valores nuevos no se muestran crudos.
        if row.get("time") in _TIME_LABEL:
            detail.append(_TIME_LABEL[row["time"]])
        else:
            # Hueco declarado: sin la franja la fila parece incompleta sin motivo.
            detail.append("hora por confirmar")
        if row.get("eps_forecast") is not None:
            detail.append(f"BPA estimado {_es_number(row['eps_forecast'], 2)}")
        events.append(
            {
                "date": day.isoformat(),
                "ticker": ticker,
                "type": "earnings",
                "title": "Resultados trimestrales",
                "detail": ", ".join(detail) or None,
                "source": SOURCE_NASDAQ,
                "origin": "cartera" if in_held else "watchlist",
            }
        )
    for row in dividends:
        ticker = str(row.get("symbol", "")).upper()
        in_held = ticker in held_us
        if not in_held and ticker not in watchlist_us:
            continue
        amount = row.get("amount")
        amount_txt = (
            f"{_es_number(amount, 4)} por acción" if isinstance(amount, (int, float)) else None
        )
        day = _parse_us_date(row.get("ex_date"))
        if day is None or not desde <= day <= hasta:
            continue
        # La fecha de pago viaja en la misma fila de NASDAQ: se muestra en el
        # detalle aunque caiga fuera del rango visible (nunca se estima).
        pay = _parse_us_date(row.get("payment_date"))
        if pay is not None:
            pay_txt = f"pago el {pay.day}/{pay.month}/{pay.year}"
            amount_txt = f"{amount_txt} · {pay_txt}" if amount_txt else pay_txt
        events.append(
            {
                "date": day.isoformat(),
                "ticker": ticker,
                "type": "dividend_ex",
                "title": "Fecha ex-dividendo",
                "detail": amount_txt,
                "source": SOURCE_NASDAQ,
                "origin": "cartera" if in_held else "watchlist",
            }
        )
    # Dividendos ingeridos: pagos de TODAS las empresas seguidas y
    # ex-dividendos no-US (los US ya salen del calendario NASDAQ en vivo).
    nasdaq_us = held_us | watchlist_us
    followed = held | watchlist
    for record in records:
        ticker = str(record.get("ticker", "")).upper()
        if ticker not in followed:
            continue
        amount = record.get("amount")
        currency = str(record.get("currency") or "").strip()
        amount_txt = (
            f"{_es_number(float(amount), 4)} {currency} por acción".strip()
            if isinstance(amount, (int, float))
            else None
        )
        origin = "cartera" if ticker in held else "watchlist"
        source = record_source_label(str(record.get("source") or ""))
        ex_day = _parse_us_date(record.get("ex_date"))
        pay_day = _parse_us_date(record.get("pay_date"))
        if ex_day is not None and desde <= ex_day <= hasta and ticker not in nasdaq_us:
            events.append(
                {
                    "date": ex_day.isoformat(),
                    "ticker": ticker,
                    "type": "dividend_ex",
                    "title": "Fecha ex-dividendo",
                    "detail": amount_txt,
                    "source": source,
                    "origin": origin,
                }
            )
        if pay_day is not None and desde <= pay_day <= hasta:
            events.append(
                {
                    "date": pay_day.isoformat(),
                    "ticker": ticker,
                    "type": "dividend_payment",
                    "title": "Pago de dividendo",
                    "detail": amount_txt,
                    "source": source,
                    "origin": origin,
                }
            )
    for action in actions:
        ticker = str(action.get("ticker", "")).upper()
        day = _parse_us_date(action.get("effective_date"))
        if ticker not in held or day is None or not desde <= day <= hasta:
            continue
        kind = str(action.get("action_type", ""))
        label = {
            "split": "Split",
            "reverse_split": "Contrasplit",
            "ticker_change": "Cambio de ticker",
            "merger": "Fusion",
            "spin_off": "Escision",
        }.get(kind, "Acción corporativa")
        ratio = action.get("ratio")
        events.append(
            {
                "date": day.isoformat(),
                "ticker": ticker,
                "type": "corporate_action",
                "title": label,
                "detail": f"ratio {_es_number(float(ratio), 4).rstrip('0').rstrip(',')}" if isinstance(ratio, (int, float)) else None,
                "source": SOURCE_GERARAI,
            }
        )
    events.sort(key=lambda e: (e["date"], _TYPE_ORDER[e["type"]], e["ticker"]))
    return events


def pending_actions(db: Session, desde: date, hasta: date) -> list[dict[str, Any]]:
    """Acciones corporativas no aplicadas con fecha efectiva en el rango."""
    rows = db.execute(
        select(CorporateAction, Company.ticker)
        .join(Company, CorporateAction.company_id == Company.id)
        .where(
            CorporateAction.applied.is_(False),
            CorporateAction.effective_date >= desde,
            CorporateAction.effective_date <= hasta,
        )
    ).all()
    return [
        {
            "ticker": ticker,
            "action_type": action.action_type,
            "effective_date": action.effective_date.isoformat(),
            "ratio": float(action.ratio),
        }
        for action, ticker in rows
    ]


def combine_status(*statuses: str) -> str:
    """ok si todo ok; unavailable si ninguna fuente externa respondio; partial si mezcla."""
    if all(s == "ok" for s in statuses):
        return "ok"
    if all(s == "unavailable" for s in statuses):
        return "unavailable"
    return "partial"
