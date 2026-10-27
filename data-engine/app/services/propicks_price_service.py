"""F2: ingesta diaria de precios para el top-N de ProPicks + metricas de momentum.

Fuente: Yahoo Finance via yfinance (gratis, sin key). Tickers EUR (BME) usan el
sufijo .MC; el resto va tal cual (universo actual: US + BME).

Momentum: rentabilidad total 6m (126 dias) y 12m (252 dias) sobre adj_close,
persistida en calculated_metrics (momentum_6m / momentum_12m, period=fecha as_of)
para que el embudo pueda ponderarla despues. Sin imputacion: si no hay serie
suficiente no se escribe metrica.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import CalculatedMetric, Company, MarketPrice, ProPickCandidate, ProPickRun

# Dias de CALENDARIO (momentum_from_series resta timedelta(days=...)): 126/252
# eran dias de bolsa y salian como ~4 y ~8 meses etiquetados 6m/12m.
MOMENTUM_WINDOWS: dict[str, int] = {"momentum_6m": 182, "momentum_12m": 365}
MIN_BARS_6M = 60   # ventanas minimas honestas (~3 meses de barras)
MIN_BARS_12M = 200
METRIC_VERSION = "v1"


# Sufijo Yahoo por bolsa del master: sin el, Yahoo resuelve el listado US por
# defecto y devuelve el gemelo americano (ALM->Almonty) o el ADR (ASML).
_US_EXCHANGE_TOKENS = ("NYSE", "NEW YORK", "NASDAQ", "AMEX", "OTC", "BATS", "ARCA")


_EXCHANGE_YAHOO_SUFFIX = {
    "BME": ".MC",
    "BOLSA DE MADRID": ".MC",
    "NYSE EURONEXT - EURONEXT AMSTERDAM": ".AS",
    "TORONTO STOCK EXCHANGE": ".TO",
    "SWISS EXCHANGE": ".SW",
    # XETRA -> .DE verificado contra Yahoo chart API 2026-09-27: SAP.DE =
    # exchange GER, divisa EUR, ~185,92 EUR (el ADR NYSE:SAP son ~210 USD).
    "XETRA": ".DE",
}


def yahoo_symbol(company: Company) -> str | None:
    """Ticker Yahoo del LISTADO REAL, o None si no hay simbolo seguro.

    Yahoo resuelve el ticker pelado en la linea US: para un emisor no-US
    devuelve el gemelo americano (TSM/TWSE -> ADR NYSE en USD guardado como
    TWD) o un homonimo (EUR sin bolsa conocida con sufijo .MC adivinado).
    Regla: bolsa mapeada -> sufijo; divisa USD -> ticker pelado (la USD es
    evidencia de linea americana: bulk import UNKNOWN, NYSE, NASDAQ, OTC);
    cualquier otra cosa -> None, y los consumidores (worker intradia y
    refresh propicks) omiten el simbolo: «sin precio» antes que el precio
    de otro instrumento."""
    ticker = (company.ticker or "").strip()
    if not ticker:
        return None
    if "." in ticker:
        return ticker
    exchange = (getattr(company, "exchange", "") or "").strip().upper()
    currency = (getattr(company, "currency", "") or "").strip().upper()
    suffix = _EXCHANGE_YAHOO_SUFFIX.get(exchange)
    if suffix:
        return f"{ticker}{suffix}"
    us_exchange = not exchange or exchange == "UNKNOWN" or any(
        token in exchange for token in _US_EXCHANGE_TOKENS
    )
    if currency == "USD" and us_exchange:
        # La USD es evidencia de linea americana (bulk import UNKNOWN, NYSE,
        # NASDAQ, OTC). Bolsa conocida no-US con USD (SHEL LSE/USD): la linea
        # US no es el instrumento que declara la bolsa -> None.
        return ticker
    return None


@dataclass(frozen=True)
class PriceBar:
    day: date
    close: Decimal
    adj_close: Decimal
    volume: int
    quote_currency: str | None = None


def fetch_history_yfinance(
    symbols: Sequence[str], *, period: str = "1y"
) -> dict[str, list[PriceBar]]:
    """Descarga OHLCV diaria via yfinance. Aislado para poder inyectarlo en tests."""
    import yfinance as yf

    out: dict[str, list[PriceBar]] = {}
    for symbol in symbols:
        try:
            instrument = yf.Ticker(symbol)
            hist = instrument.history(period=period, auto_adjust=False)
        except Exception:
            out[symbol] = []
            continue
        try:
            unit = instrument.get_history_metadata().get("currency")
        except Exception:
            unit = None
        bars: list[PriceBar] = []
        for idx, row in hist.iterrows():
            close = row.get("Close")
            adj = row.get("Adj Close", close)
            if close is None or adj is None:
                continue
            # yfinance devuelve NaN en dias sin cierre: un NaN guardado hacia
            # que el calculo de momentum lanzase InvalidOperation y el job
            # entero abortase sin escribir nada.
            try:
                if not (math.isfinite(float(close)) and math.isfinite(float(adj))):
                    continue
            except (TypeError, ValueError):
                continue
            bars.append(
                PriceBar(
                    day=idx.date(),
                    close=Decimal(str(round(float(close), 6))),
                    adj_close=Decimal(str(round(float(adj), 6))),
                    volume=int(row.get("Volume") or 0),
                    quote_currency=unit,
                )
            )
        out[symbol] = bars
    return out


_NY = ZoneInfo("America/New_York")
# Una barra del dia en curso solo es cierre oficial cuando la sesion US ya
# termino (misma regla que market_close_sync._SESSION_CLOSED_AFTER).
_SESSION_CLOSED_AFTER = (16, 30)


def _us_session_open(now: datetime) -> bool:
    local = now.astimezone(_NY)
    if local.weekday() >= 5:
        return False
    return (local.hour, local.minute) < _SESSION_CLOSED_AFTER


def upsert_prices(
    db: Session,
    company: Company,
    bars: Iterable[PriceBar],
    *,
    now: datetime | None = None,
) -> int:
    """Upsert por (company_id, date). Devuelve barras escritas.

    Con la sesion US abierta la barra de hoy es una foto intradia, no un
    cierre: se descarta siempre. Estas filas se leen como cierre oficial
    (source="yfinance") en Movers, Mercado y watchlist, y una foto intradia
    escrita aquí salía en /screener como «Cierre {hoy}» a media sesión.
    """
    now = now or datetime.now(UTC)
    skip_today = _us_session_open(now)
    today_ny = now.astimezone(_NY).date()
    written = 0
    for bar in bars:
        if skip_today and bar.day >= today_ny:
            continue
        values = {
            "company_id": company.id,
            "date": bar.day,
            "open": bar.close,
            "high": bar.close,
            "low": bar.close,
            "close": bar.close,
            "adj_close": bar.adj_close,
            "volume": bar.volume,
            "source": "yfinance",
            "quote_currency": bar.quote_currency,
        }
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            stmt = pg_insert(MarketPrice).values(**values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_market_price_company_date",
                set_={
                    "close": stmt.excluded.close,
                    "adj_close": stmt.excluded.adj_close,
                    "volume": stmt.excluded.volume,
                    "source": stmt.excluded.source,
                    "quote_currency": stmt.excluded.quote_currency,
                },
            )
            db.execute(stmt)
        else:
            existing = db.scalar(
                select(MarketPrice).where(
                    MarketPrice.company_id == company.id,
                    MarketPrice.date == bar.day,
                )
            )
            if existing is not None:
                existing.close = bar.close
                existing.adj_close = bar.adj_close
                existing.volume = bar.volume
                existing.source = "yfinance"
                existing.quote_currency = bar.quote_currency
            else:
                db.add(MarketPrice(**values))
        written += 1
    return written


def momentum_from_series(series: Sequence[tuple[date, Decimal]], days: int) -> Decimal | None:
    """Rentabilidad entre el ultimo adj_close y el mas cercano a `days` atras.

    `series` ordenada ascendente por fecha. None si no hay datos suficientes.
    """
    if len(series) < 2:
        return None
    last_day, last_px = series[-1]
    target = last_day - timedelta(days=days)
    past = [(d, p) for d, p in series if d <= target]
    if not past:
        return None
    past_day, past_px = past[-1]
    # Exigimos que el punto pasado este razonablemente cerca del objetivo
    # (+-20 dias) para no vender como 6m un retorno de 2 semanas.
    if abs((past_day - target).days) > 20:
        return None
    if past_px <= 0:
        return None
    return (last_px - past_px) / past_px


def compute_momentum_metrics(
    db: Session,
    companies: Sequence[Company],
    *,
    as_of: date,
) -> dict[str, int]:
    """Calcula y persiste momentum_6m/12m en calculated_metrics."""
    tenant_id = db.info.get("tenant_id")
    stats = {"momentum_6m": 0, "momentum_12m": 0, "skipped": 0}
    for company in companies:
        rows = db.execute(
            select(MarketPrice.date, MarketPrice.adj_close)
            .where(MarketPrice.company_id == company.id, MarketPrice.date <= as_of)
            .order_by(MarketPrice.date)
        ).all()
        # F370: solo barras hasta as_of; un as_of historico no puede usar datos
        # posteriores etiquetados con la fecha pedida.
        series = [
            (d, Decimal(str(p)))
            for d, p in rows
            if p is not None and Decimal(str(p)).is_finite() and p > 0
        ]
        if len(series) < MIN_BARS_6M:
            stats["skipped"] += 1
            continue
        for metric, days in MOMENTUM_WINDOWS.items():
            if len(series) < (MIN_BARS_12M if days > 182 else MIN_BARS_6M):
                continue
            value = momentum_from_series(series, days)
            if value is None:
                continue
            existing = db.scalar(
                select(CalculatedMetric).where(
                    CalculatedMetric.tenant_id == tenant_id,
                    CalculatedMetric.company_id == company.id,
                    CalculatedMetric.metric == metric,
                    CalculatedMetric.period == as_of.isoformat(),
                    CalculatedMetric.definition_version == METRIC_VERSION,
                )
            )
            if existing is not None:
                existing.value = value
                existing.calculation_trace = {
                    "window_days": days,
                    "as_of": as_of.isoformat(),
                    "last_bar_date": series[-1][0].isoformat(),
                }
            else:
                db.add(
                    CalculatedMetric(
                        tenant_id=tenant_id,
                        company_id=company.id,
                        metric=metric,
                        value=value,
                        unit="decimal",
                        period=as_of.isoformat(),
                        fiscal_year=as_of.year,
                        status="ok",
                        definition_version=METRIC_VERSION,
                        formula=f"adj_close(t)/adj_close(t-{days}d) - 1 sobre market_prices (yfinance)",
                        numerator=None,
                        denominator=None,
                        source_fact_ids=[],
                        calculation_trace={
                            "window_days": days,
                            "as_of": as_of.isoformat(),
                            "last_bar_date": series[-1][0].isoformat(),
                        },
                    )
                )
            stats[metric] += 1
    db.flush()
    return stats


def latest_run_passed_companies(db: Session, *, limit: int = 500) -> list[Company]:
    """Todas las aprobadas del ultimo run completado (rank primero, luego score).

    Las joyas ocultas viven fuera del top-N: el top del embudo de calidad son
    mega-caps, y las gemas (cap 300M-10.000M) estan mas abajo del ranking. Si
    solo se refrescan precios del top-N, ninguna aprobada pequena tiene precio
    fresco y `find_gems` devuelve una lista vacia.
    """
    run = db.scalar(
        select(ProPickRun)
        .where(
            ProPickRun.status == "completed",
            *tenant_filters(db, ProPickRun),
        )
        .order_by(desc(ProPickRun.id))
        .limit(1)
    )
    if run is None:
        return []
    rows = db.execute(
        select(Company)
        .join(ProPickCandidate, ProPickCandidate.company_id == Company.id)
        .where(
            ProPickCandidate.run_id == run.id,
            ProPickCandidate.passed.is_(True),
            *tenant_filters(db, ProPickCandidate),
        )
        .order_by(
            ProPickCandidate.rank.asc().nulls_last(),
            ProPickCandidate.score.desc(),
        )
        .limit(limit)
    ).scalars().all()
    return list(rows)


def latest_run_top_companies(db: Session, *, top_n: int = 40) -> list[Company]:
    """Top-N aprobadas del ultimo run completado del embudo."""
    run = db.scalar(
        select(ProPickRun)
        .where(
            ProPickRun.status == "completed",
            *tenant_filters(db, ProPickRun),
        )
        .order_by(desc(ProPickRun.id))
        .limit(1)
    )
    if run is None:
        return []
    rows = db.execute(
        select(Company)
        .join(ProPickCandidate, ProPickCandidate.company_id == Company.id)
        .where(
            ProPickCandidate.run_id == run.id,
            ProPickCandidate.passed.is_(True),
            *tenant_filters(db, ProPickCandidate),
        )
        .order_by(ProPickCandidate.rank)
        .limit(top_n)
    ).scalars().all()
    return list(rows)


def refresh_propicks_prices(
    db: Session,
    *,
    top_n: int = 40,
    max_companies: int = 500,
    period: str = "2y",  # 12m de momentum exige > 365 dias de historia
    fetcher: Callable[..., dict[str, list[PriceBar]]] = fetch_history_yfinance,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Job F2: precios diarios + momentum del embudo.

    Cobertura de precios: TODAS las aprobadas del ultimo run (hasta
    ``max_companies``), no solo el top-N rankeado. Con cobertura solo top-N,
    ninguna empresa pequena llegaba a tener precio fresco y la pantalla de
    joyas salia sistematicamente vacia (top de calidad = mega-caps, fuera de
    la banda 300M-10.000M). El momentum se calcula para toda empresa con
    serie suficiente; ``top_n`` queda como parametro legacy aceptado por
    compatibilidad de llamadas existentes.
    """
    as_of = as_of or date.today()
    companies = latest_run_passed_companies(db, limit=max_companies)
    if not companies:
        return {"status": "skipped", "reason": "no completed propick run", "companies": 0}
    symbols = {s: c for c in companies if (s := yahoo_symbol(c)) is not None}
    history = fetcher(list(symbols), period=period)
    bars_written = 0
    covered: list[Company] = []
    for symbol, company in symbols.items():
        bars = history.get(symbol) or []
        if not bars:
            continue
        bars_written += upsert_prices(db, company, bars)
        covered.append(company)
    momentum = compute_momentum_metrics(db, covered, as_of=as_of)
    db.commit()
    return {
        "status": "ok",
        "companies": len(companies),
        "covered": len(covered),
        "bars_written": bars_written,
        "momentum": momentum,
        "as_of": as_of.isoformat(),
    }
