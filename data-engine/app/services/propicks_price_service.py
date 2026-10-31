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

import sqlalchemy as sa
from sqlalchemy import and_, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import CalculatedMetric, Company, MarketPrice, ProPickCandidate, ProPickRun
from app.services import movers_cache
from app.services.connectors.yahoo import yahoo_chart_symbol
from app.valuation.currency import SUFFIX_QUOTE_UNIT, listing_quote_unit, normalize_currency

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
    # Mismos alias que wacc_input_service (F156): en prod el exchange llega
    # tambien como «EURONEXT AMSTERDAM» o «NYSE EURONEXT - AMSTERDAM».
    "EURONEXT AMSTERDAM": ".AS",
    "NYSE EURONEXT - AMSTERDAM": ".AS",
    "TORONTO STOCK EXCHANGE": ".TO",
    "SWISS EXCHANGE": ".SW",
    # XETRA -> .DE verificado contra Yahoo chart API 2026-09-27: SAP.DE =
    # exchange GER, divisa EUR, ~185,92 EUR (el ADR NYSE:SAP son ~210 USD).
    "XETRA": ".DE",
    "DEUTSCHE BOERSE AG": ".DE",
    # Londres y Euronext (verificado con yfinance 2026-10-27): SHEL.L = LSE en
    # GBp, CGEO.L = LSE en GBp, MC.PA = Paris en EUR, ABI.BR = Bruselas en EUR,
    # GALP.LS = Lisboa en EUR, ENI.MI = Milan en EUR. Ojo: el sufijo .L NO fija
    # la divisa (SMSN.L y CSPX.L cotizan en USD); la divisa del precio es la que
    # Yahoo declara para la cotizacion (PriceBar.quote_currency), nunca la de
    # las cuentas de la empresa.
    "LONDON STOCK EXCHANGE": ".L",
    "EURONEXT PARIS": ".PA",
    "NYSE EURONEXT - EURONEXT PARIS": ".PA",
    "NYSE EURONEXT - PARIS": ".PA",
    "EURONEXT BRUSSELS": ".BR",
    "NYSE EURONEXT - EURONEXT BRUSSELS": ".BR",
    "NYSE EURONEXT - BRUSSELS": ".BR",
    "EURONEXT LISBON": ".LS",
    "NYSE EURONEXT - EURONEXT LISBON": ".LS",
    "NYSE EURONEXT - LISBON": ".LS",
    "BORSA ITALIANA": ".MI",
    "EURONEXT MILAN": ".MI",
    "MILAN STOCK EXCHANGE": ".MI",
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
    from app.services.listing_identity import reviewed_listing

    listing = reviewed_listing(getattr(company, "isin", None))
    if listing:
        # Known issuer but conflicting master currency: never label EUR bars USD.
        return listing.yahoo if company.currency == listing.currency else None
    ticker = (company.ticker or "").strip()
    if not ticker:
        return None
    if "." in ticker:
        # Clase US con punto (BRK.B, convencion del master) -> guion (BRK-B):
        # yfinance no devuelve barras para «BRK.B». Un sufijo de bolsa
        # (SAN.MC, CGEO.L) pasa intacto.
        return yahoo_chart_symbol(ticker)
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
        # NASDAQ, OTC). Bolsa conocida no-US sin sufijo mapeado con USD: la
        # linea US no es el instrumento que declara la bolsa -> None. (SHEL
        # LSE/USD ya no llega aqui: Londres mapea a .L, la linea de Londres.)
        return ticker
    return None


def _symbol_suffix(symbol: str) -> str | None:
    text = symbol.strip().upper()
    return "." + text.rsplit(".", 1)[1] if "." in text else None


def bar_unit_is_known(company: Company, bar: PriceBar) -> bool:
    """¿Se sabe en que divisa esta esta barra?

    La divisa del precio es la que Yahoo declara para la cotizacion
    (``quote_currency``). Sin ella, los lectores caen a la unidad del listado
    deducida del ticker y de ``Company.currency`` (price_units). Esa deduccion
    solo vale si coincide con la unidad por defecto de la plaza del simbolo
    Yahoo: SHEL (LSE, cuentas en USD) -> SHEL.L cotiza en peniques, y una
    barra sin divisa se leeria como 3.927 USD. En ese caso la barra no se
    guarda: «sin precio» antes que un precio en otra divisa."""
    if bar.quote_currency:
        return True
    symbol = yahoo_symbol(company) or (company.ticker or "")
    suffix = _symbol_suffix(symbol)
    venue_unit = SUFFIX_QUOTE_UNIT.get(suffix) if suffix else None
    if venue_unit is None:
        return True
    declared_unit = listing_quote_unit(company.ticker, getattr(company, "currency", None))
    return normalize_currency(venue_unit) == normalize_currency(declared_unit)


@dataclass(frozen=True)
class PriceBar:
    day: date
    close: Decimal
    adj_close: Decimal
    volume: int
    quote_currency: str | None = None
    market_timezone: str | None = None
    session_end: datetime | None = None


def _volume(raw: Any) -> int:
    """Volumen entero; NaN/None/no numerico -> 0.

    yfinance devuelve Volume=NaN en algunas sesiones (indices, LSE, dias
    festivos parciales). ``int(nan)`` lanzaba ValueError fuera del try por
    simbolo y abortaba la descarga ENTERA del lote: ningun cierre escrito.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0
    return int(value) if math.isfinite(value) and value > 0 else 0


def fetch_history_yfinance(
    symbols: Sequence[str], *, period: str = "1y"
) -> dict[str, list[PriceBar]]:
    """Descarga OHLCV diaria via yfinance. Aislado para poder inyectarlo en tests."""
    import yfinance as yf

    out: dict[str, list[PriceBar]] = {}
    for symbol in symbols:
        try:
            instrument = yf.Ticker(symbol)
            if period == "7d":
                # Yahoo range=7d can return NULL closes for completed sessions
                # while the same daily history with explicit bounds has values.
                # Preserve daily bars, source units and the final-session gate.
                today = datetime.now(UTC).date()
                hist = instrument.history(
                    start=(today - timedelta(days=7)).isoformat(),
                    end=(today + timedelta(days=1)).isoformat(),
                    auto_adjust=False,
                )
            else:
                hist = instrument.history(period=period, auto_adjust=False)
        except Exception:
            out[symbol] = []
            continue
        try:
            metadata = instrument.get_history_metadata() or {}
        except Exception:
            metadata = {}
        unit = metadata.get("currency")
        timezone = metadata.get("exchangeTimezoneName")
        regular = (metadata.get("currentTradingPeriod") or {}).get("regular") or {}
        end = regular.get("end")
        session_end = datetime.fromtimestamp(end, UTC) if isinstance(end, (int, float)) else None
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
                    volume=_volume(row.get("Volume")),
                    quote_currency=unit,
                    market_timezone=timezone,
                    session_end=session_end,
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


def _bar_is_final(company: Company, bar: PriceBar, now: datetime) -> bool:
    """La fuente manda sobre el reloj. Sin metadatos no se adivina bolsa por ticker."""
    try:
        zone = ZoneInfo(bar.market_timezone) if bar.market_timezone else None
    except (KeyError, ValueError):
        zone = None
    if zone is not None:
        today = now.astimezone(zone).date()
        if bar.day < today:
            return True
        if bar.day > today:
            return False
        end = bar.session_end
        return bool(end and end.astimezone(zone).date() == bar.day and now >= end)
    exchange = (company.exchange or "").upper()
    if any(token in exchange for token in _US_EXCHANGE_TOKENS):
        today = now.astimezone(_NY).date()
        return bar.day < today or (bar.day == today and not _us_session_open(now))
    # Un dia UTC completo de margen evita tratar un dia local desconocido
    # como cerrado. No se publica la barra reciente sin evidencia del mercado.
    return bar.day < now.astimezone(UTC).date() - timedelta(days=1)


def upsert_prices(
    db: Session,
    company: Company,
    bars: Iterable[PriceBar],
    *,
    now: datetime | None = None,
) -> int:
    """Upsert por (company_id, date). Devuelve barras escritas.

    La barra actual requiere fin de sesión y zona de mercado de la fuente.
    Sin metadatos, solo la bolsa US explícita conserva el gate conservador
    anterior; para otros mercados se dejan pasar solo días antiguos. Estas filas se leen como cierre oficial
    (source="yfinance") en Movers, Mercado y watchlist, y una foto intradia
    escrita aquí salía en /screener como «Cierre {hoy}» a media sesión.
    """
    now = now or datetime.now(UTC)
    written = 0
    for bar in bars:
        if not _bar_is_final(company, bar, now):
            continue
        if not bar_unit_is_known(company, bar):
            continue
        # Volumen ausente (yfinance NaN -> 0) es NULL, nunca un 0 fabricado
        # (contrato del modelo: 0 coronaba al ticker como el menos activo).
        volume = bar.volume if bar.volume > 0 else None
        values = {
            "company_id": company.id,
            "date": bar.day,
            "open": bar.close,
            "high": bar.close,
            "low": bar.close,
            "close": bar.close,
            "adj_close": bar.adj_close,
            "volume": volume,
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
                    # Un re-sync sin volumen (NaN de la fuente) NO pisa el
                    # volumen real ya guardado: ausente no borra dato.
                    "volume": sa.func.coalesce(stmt.excluded.volume, MarketPrice.volume),
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
                # Igual que la via Postgres: ausente no borra dato real.
                if volume is not None:
                    existing.volume = volume
                existing.source = "yfinance"
                existing.quote_currency = bar.quote_currency
            else:
                db.add(MarketPrice(**values))
        written += 1
    if written:
        # Movers cachea el cálculo de cierres: se invalida tras el commit.
        movers_cache.mark_prices_written(db)
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
    """Calcula y persiste momentum_6m/12m en calculated_metrics.

    Tres consultas para todo el lote (antes ~3 por empresa): recuento de
    barras validas y ultima fecha VALIDA por empresa sobre TODA la historia
    (los umbrales MIN_BARS no cambian), barras solo de la ventana que el
    momentum puede mirar y metricas ya persistidas para este as_of. La
    ingesta rechaza cierres no finitos, asi que IS NOT NULL + > 0 equivale
    al filtro de finitud del calculo original.

    La ventana es [d0 - 405 dias, d0] por empresa: el punto pasado de 12m
    esta como mucho a 365+20 dias de la ultima barra d0, y un punto mas
    viejo seria rechazado por la regla de +-20 dias de momentum_from_series,
    asi que acotar no cambia ningun resultado.
    """
    tenant_id = db.info.get("tenant_id")
    stats = {"momentum_6m": 0, "momentum_12m": 0, "skipped": 0}
    if not companies:
        return stats

    valid_price = and_(MarketPrice.adj_close.is_not(None), MarketPrice.adj_close > 0)
    company_ids = [c.id for c in companies]
    totals = {
        cid: (int(n), d0)
        for cid, n, d0 in db.execute(
            select(
                MarketPrice.company_id,
                func.count().filter(valid_price),
                func.max(MarketPrice.date).filter(valid_price),
            )
            .where(MarketPrice.company_id.in_(company_ids), MarketPrice.date <= as_of)
            .group_by(MarketPrice.company_id)
        )
    }
    eligible = [
        c
        for c in companies
        if (t := totals.get(c.id)) is not None and t[0] >= MIN_BARS_6M and t[1] is not None
    ]
    stats["skipped"] = len(companies) - len(eligible)
    if not eligible:
        return stats

    window_start = min(totals[c.id][1] for c in eligible) - timedelta(days=405)
    bars: dict[int, list[tuple[date, Decimal]]] = {c.id: [] for c in eligible}
    for cid, day, px in db.execute(
        select(MarketPrice.company_id, MarketPrice.date, MarketPrice.adj_close)
        .where(
            MarketPrice.company_id.in_([c.id for c in eligible]),
            MarketPrice.date <= as_of,
            MarketPrice.date >= window_start,
            valid_price,
        )
        .order_by(MarketPrice.company_id, MarketPrice.date)
    ):
        price = Decimal(str(px))
        if price.is_finite():
            bars[cid].append((day, price))

    existing = {
        (m.company_id, m.metric): m
        for m in db.scalars(
            select(CalculatedMetric).where(
                CalculatedMetric.tenant_id == tenant_id,
                CalculatedMetric.company_id.in_([c.id for c in eligible]),
                CalculatedMetric.metric.in_(MOMENTUM_WINDOWS),
                CalculatedMetric.period == as_of.isoformat(),
                CalculatedMetric.definition_version == METRIC_VERSION,
            )
        )
    }

    for company in eligible:
        n_bars, d0 = totals[company.id]
        series = [
            (day, price)
            for day, price in bars[company.id]
            if day >= d0 - timedelta(days=405)
        ]
        for metric, days in MOMENTUM_WINDOWS.items():
            if n_bars < (MIN_BARS_12M if days > 182 else MIN_BARS_6M):
                continue
            value = momentum_from_series(series, days)
            if value is None:
                continue
            trace = {
                "window_days": days,
                "as_of": as_of.isoformat(),
                "last_bar_date": series[-1][0].isoformat(),
            }
            row = existing.get((company.id, metric))
            if row is not None:
                row.value = value
                row.calculation_trace = trace
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
                        calculation_trace=trace,
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
