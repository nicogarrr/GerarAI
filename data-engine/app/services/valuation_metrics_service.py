"""Metricas de valoracion dependientes de precio: P/B y yield TTM de dividendo.

Mismo patron que el momentum F2 (propicks_price_service): se calculan tras la
ingesta diaria de cierres y se persisten en ``calculated_metrics`` con
``period`` = as_of ISO, ``definition_version`` propia y ``calculation_trace``
con la fuente y fecha de cada input. Sin dato fiable la metrica NO se escribe:
la ausencia es N/D, nunca un valor inventado ni imputado.

price_to_book = close / (total_equity / shares_diluted) del mismo FY:
  - ``total_equity`` <= 0 -> sin metrica (un P/B sobre patrimonio neto
    negativo no informa y se prestaria a lecturas falsas).
  - FY con mas de ``MAX_FY_AGE_YEARS`` anos -> sin metrica (precedente VOYA en
    gems: un FY viejo contra el precio de hoy no es un dato actual).
  - divisa de los hechos (``FinancialFact.unit``) distinta de la divisa de
    cotizacion (``Company.currency``) -> sin metrica: nunca se mezclan
    divisas (GBp queda fuera por ser zona congelada: Company.currency="GBp"
    no casa con hechos en GBP y el fail-closed lo excluye solo).

dividend_yield_ttm = dividendos por accion de los ultimos 365 dias / close:
  - Fuente primaria: eventos de dividendo de Yahoo Finance. NO OFICIAL: la
    etiqueta ``YAHOO_LABEL`` viaja en la formula y en calculation_trace de
    cada fila.
  - Contraste: Finnhub ``dividendYieldIndicatedAnnual`` cuando hay key. Si
    difiere del TTM de Yahoo mas de ``DISAGREE_REL_TOL`` en relativo, la
    fila se guarda con status ``fuentes_en_desacuerdo`` y la traza lleva
    AMBAS cifras: el desacuerdo se muestra; nunca se elige una fuente en
    silencio.
  - Error de la fuente (red, ticker sin pagina) -> fetcher devuelve None y
    NO se escribe nada; ``[]`` (sin dividendos registrados en 12m) si se
    escribe como yield 0 con la etiqueta correspondiente.

Hermeticidad en tests: los fetchers por defecto salen a red (yfinance /
Finnhub) y estan vetados bajo pytest; los tests inyectan fetchers con
fixtures grabadas.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import CalculatedMetric, Company, FinancialFact, MarketPrice
from app.services.price_units import close_in_company_currency
from app.services.propicks_price_service import yahoo_symbol
from app.services.split_adjustment import (
    fact_split_factor,
    split_after_price,
    split_events_by_company,
)
from app.valuation.engines.base import ADR_TAG_PREFIX, adr_ratio

METRIC_VERSION = "valuation-v1"
PRICE_FRESHNESS_DAYS = 7
MAX_FY_AGE_YEARS = 2
DIVIDEND_WINDOW_DAYS = 365
DISAGREE_REL_TOL = Decimal("0.10")
EXTREME_YIELD = Decimal("0.25")
YAHOO_LABEL = "Yahoo Finance (fuente no oficial)"
FINNHUB_LABEL = "Finnhub (dividendo indicado anual)"
STATUS_OK = "ok"
STATUS_DISAGREE = "fuentes_en_desacuerdo"

METRIC_PB = "price_to_book"
METRIC_YIELD = "dividend_yield_ttm"

# fetcher de dividendos: symbol Yahoo -> [{date, amount}] o None si la fuente
# fallo (None != []: [] afirma "sin dividendos", None afirma "no lo se").
DividendFetcher = Callable[[str], list[dict[str, Any]] | None]
# fetcher de contraste: ticker -> yield anual indicado en fraccion (0.023) o None.
FinnhubYieldFetcher = Callable[[str], Decimal | None]


def _network_forbidden_in_tests() -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError(
            "Red vetada en tests: inyecta dividend_fetcher / finnhub_yield_fetcher"
        )


def default_dividend_fetcher(symbol: str) -> list[dict[str, Any]] | None:
    """Eventos de dividendo de yfinance. None si la fuente no responde."""
    _network_forbidden_in_tests()
    import yfinance as yf

    try:
        series = yf.Ticker(symbol).dividends
    except Exception:
        return None
    if series is None:
        return None
    events: list[dict[str, Any]] = []
    for idx, amount in series.items():
        try:
            qty = Decimal(str(round(float(amount), 6)))
        except (TypeError, ValueError, InvalidOperation):
            continue
        if not qty.is_finite() or qty < 0:
            continue
        events.append({"date": idx.date().isoformat(), "amount": str(qty)})
    return events


def default_finnhub_yield_fetcher(ticker: str) -> Decimal | None:
    """dividendYieldIndicatedAnnual de Finnhub en fraccion. None si no aplica."""
    _network_forbidden_in_tests()
    from app.core.config import get_settings

    if not get_settings().finnhub_api_key:
        return None
    from app.services.connectors.finnhub import FinnhubClient
    from app.services.thesis_evidence_service import _await_sync

    try:
        metric = _await_sync(lambda: FinnhubClient().metric(ticker))
    except Exception:
        return None
    raw = metric.get("dividendYieldIndicatedAnnual")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not value.is_finite() or value < 0:
        return None
    return value / Decimal(100)


def _latest_price(
    db: Session, company_id: int, as_of: date
) -> tuple[Decimal, date, str | None, str | None] | None:
    """Ultimo cierre <= as_of con frescura <= PRICE_FRESHNESS_DAYS
    (cierre, fecha, fuente, divisa de cotizacion).

    Nunca un precio posterior a as_of (point-in-time, precedente F370) ni un
    precio viejo presentado como actual (precedente del track record).
    """
    row = db.scalar(
        select(MarketPrice)
        .where(MarketPrice.company_id == company_id, MarketPrice.date <= as_of)
        .order_by(MarketPrice.date.desc())
        .limit(1)
    )
    if row is None or row.close is None:
        return None
    close = Decimal(str(row.close))
    if not close.is_finite() or close <= 0:
        return None
    if (as_of - row.date).days > PRICE_FRESHNESS_DAYS:
        return None
    return close, row.date, getattr(row, "source", None), getattr(row, "quote_currency", None)


def _book_value_per_share(
    db: Session, company: Company, as_of: date, price_date: date | None = None
) -> dict[str, Any] | None:
    """total_equity / shares_diluted del mismo FY reciente, con control de divisa."""
    min_fy = as_of.year - MAX_FY_AGE_YEARS
    rows = db.execute(
        select(
            FinancialFact.metric,
            FinancialFact.fiscal_year,
            FinancialFact.value,
            FinancialFact.unit,
            FinancialFact.source_type,
            FinancialFact.period,
            FinancialFact.filed,
        )
        .where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric.in_(["total_equity", "shares_diluted"]),
            FinancialFact.fiscal_quarter.in_(["FY", ""]),
            FinancialFact.fiscal_year.isnot(None),
            FinancialFact.fiscal_year >= min_fy,
            *tenant_filters(db, FinancialFact),
        )
        .order_by(FinancialFact.fiscal_year.desc(), FinancialFact.created_at.desc())
    ).all()
    by_metric: dict[str, tuple[int, Decimal, str, str, str | None, date | None]] = {}
    for metric, fy, value, unit, source_type, period, filed in rows:
        by_metric.setdefault(
            metric, (fy, Decimal(str(value)), unit or "", source_type or "", period, filed)
        )
    if "total_equity" not in by_metric or "shares_diluted" not in by_metric:
        return None
    eq_fy, equity, eq_unit, eq_src, _eq_period, _eq_filed = by_metric["total_equity"]
    sh_fy, shares, sh_unit, sh_src, sh_period, sh_filed = by_metric["shares_diluted"]
    if eq_fy != sh_fy:
        return None  # equity y acciones de ejercicios distintos: no se mezclan
    if equity <= 0 or shares <= 0:
        return None
    # Comparacion EXACTA y sensible a mayusculas: "GBP" (libras) != "GBp"
    # (peniques). Un upper() aqui equiparaba pence con libras y el P/B salia
    # 100 veces inflado. Fail-closed ante cualquier diferencia de rotulo.
    quote_ccy = (company.currency or "").strip()
    if not quote_ccy or eq_unit.strip() != quote_ccy:
        return None  # divisa de hechos != divisa de cotizacion: fail-closed
    # Los hechos de un emisor extranjero vienen por accion ORDINARIA y el
    # precio de un ADR es por ADR (N ordinarias): sin el ratio el P/B salia
    # N veces inflado. Libros por ADR = libros por ordinaria x N; una ficha
    # marcada ADR sin ratio valido no tiene P/B (fail-closed).
    ratio = adr_ratio(company)
    tagged_adr = any(
        str(tag).strip().lower() == "adr" or str(tag).strip().lower().startswith(ADR_TAG_PREFIX)
        for tag in (company.factor_tags or [])
    )
    if ratio is None and tagged_adr:
        return None
    # El precio es del dia; las acciones, del cierre del ejercicio. Un split
    # posterior (efectivo entre el cierre y la fecha del precio) cambia el
    # recuento: acciones actuales = filing x factor acumulado. Sin ajuste un
    # 10:1 dejaba el P/B dividido entre 10 (misma regla que el screener).
    # Un 10-K publicado DESPUES del split ya trae las acciones reexpresadas:
    # misma regla que el DCF (fact_split_factor, consciente del `filed`).
    events = split_events_by_company(db, [company.id]).get(company.id, [])
    # Cierre anterior a un split ya efectivo: base del precio desconocida
    # (vieja o ya ajustada por el proveedor): P/B N/D, como la valoracion
    # (#3227); nunca un P/B que puede salir x factor.
    if price_date is not None and split_after_price(events, price_date, as_of):
        return None
    split_factor = fact_split_factor(
        events,
        period=sh_period,
        filed=sh_filed,
        cutoff=price_date or as_of,
    )
    bvps = equity / (shares * split_factor) * (Decimal(str(ratio)) if ratio else Decimal(1))
    return {
        "bvps": bvps,
        "adr_ratio": ratio,
        "split_factor": split_factor,
        "fiscal_year": eq_fy,
        "equity": equity,
        "shares": shares,
        "fact_unit": eq_unit,
        "equity_source": eq_src,
        "shares_source": sh_src,
    }


def ttm_dividend_per_share(
    events: list[dict[str, Any]], as_of: date
) -> tuple[Decimal, list[dict[str, Any]]]:
    """Suma dividendos con ex-fecha en (as_of - 365d, as_of]. Devuelve (ttm, usados)."""
    window_start = as_of - timedelta(days=DIVIDEND_WINDOW_DAYS)
    total = Decimal(0)
    used: list[dict[str, Any]] = []
    for event in events:
        try:
            day = date.fromisoformat(str(event["date"]))
            amount = Decimal(str(event["amount"]))
        except (KeyError, ValueError, InvalidOperation):
            continue
        if not amount.is_finite() or amount < 0:
            continue
        if not (window_start < day <= as_of):
            continue  # fuera de ventana o posterior al corte: no era conocible
        total += amount
        used.append({"date": day.isoformat(), "amount": str(amount)})
    return total, used


def _rel_disagree(a: Decimal, b: Decimal) -> Decimal:
    top = max(a, b)
    if top == 0:
        return Decimal(0)
    return abs(a - b) / top


def _upsert_metric(
    db: Session,
    *,
    tenant_id: int,
    company_id: int,
    metric: str,
    value: Decimal,
    as_of: date,
    status: str,
    formula: str,
    trace: dict[str, Any],
) -> None:
    existing = db.scalar(
        select(CalculatedMetric).where(
            CalculatedMetric.tenant_id == tenant_id,
            CalculatedMetric.company_id == company_id,
            CalculatedMetric.metric == metric,
            CalculatedMetric.period == as_of.isoformat(),
            CalculatedMetric.definition_version == METRIC_VERSION,
        )
    )
    if existing is not None:
        existing.value = value
        existing.status = status
        existing.calculation_trace = trace
        return
    db.add(
        CalculatedMetric(
            tenant_id=tenant_id,
            company_id=company_id,
            metric=metric,
            value=value,
            unit="decimal",
            period=as_of.isoformat(),
            fiscal_year=as_of.year,
            status=status,
            definition_version=METRIC_VERSION,
            formula=formula,
            numerator=None,
            denominator=None,
            source_fact_ids=[],
            calculation_trace=trace,
        )
    )


def compute_valuation_metrics(
    db: Session,
    companies: Sequence[Company],
    *,
    as_of: date,
    dividend_fetcher: DividendFetcher | None = None,
    finnhub_yield_fetcher: FinnhubYieldFetcher | None = None,
) -> dict[str, Any]:
    """Calcula y persiste price_to_book y dividend_yield_ttm por empresa.

    Fetchers inyectables: en prod salen a yfinance/Finnhub; en tests se
    inyectan fixtures (la red por defecto esta vetada bajo pytest).
    """
    if dividend_fetcher is None:
        dividend_fetcher = default_dividend_fetcher
    if finnhub_yield_fetcher is None:
        finnhub_yield_fetcher = default_finnhub_yield_fetcher
    tenant_id = db.info.get("tenant_id")
    stats: dict[str, Any] = {
        METRIC_PB: 0,
        METRIC_YIELD: 0,
        "desacuerdo_fuentes": 0,
        "yield_extremo_revisar": 0,
        "skipped": {
            "sin_precio_fresco": 0,
            "sin_libros": 0,
            "sin_fx_cotizacion": 0,
            "sin_simbolo_yahoo": 0,
            "dividendos_fuente_fallo": 0,
        },
    }
    for company in companies:
        price = _latest_price(db, company.id, as_of)
        if price is None:
            stats["skipped"]["sin_precio_fresco"] += 1
            continue
        close, price_date, price_source, quote_currency = price

        book = _book_value_per_share(db, company, as_of, price_date)
        # Los libros van en Company.currency y el cierre en la divisa de
        # cotizacion: TSCO.L cotiza en GBp y reporta en GBP (250 peniques son
        # 2,50 GBP; sin pasar a libras el P/B salia x100); SHEL.L en GBp con
        # cuentas en USD necesita FX point-in-time. Sin tipo valido: N/D.
        pb_close = (
            close_in_company_currency(
                db, close, quote_currency=quote_currency, company=company, on=price_date,
            )
            if book is not None
            else None
        )
        if book is None:
            stats["skipped"]["sin_libros"] += 1
        elif pb_close is None:
            stats["skipped"]["sin_fx_cotizacion"] += 1
        else:
            pb = pb_close / book["bvps"]
            _upsert_metric(
                db,
                tenant_id=tenant_id,
                company_id=company.id,
                metric=METRIC_PB,
                value=pb,
                as_of=as_of,
                status=STATUS_OK,
                formula=(
                    "close(market_prices) / (total_equity/shares_diluted del "
                    "mismo FY, hechos persistidos)"
                ),
                trace={
                    "as_of": as_of.isoformat(),
                    "price": str(pb_close),
                    "quote_close": str(close),
                    "quote_currency": quote_currency,
                    "price_date": price_date.isoformat(),
                    "price_source": price_source,
                    "fiscal_year": book["fiscal_year"],
                    "total_equity": str(book["equity"]),
                    "shares_diluted": str(book["shares"]),
                    "fact_unit": book["fact_unit"],
                    "adr_ratio": book["adr_ratio"],
                    "split_factor": format(book["split_factor"].normalize(), "f"),
                    "equity_source": book["equity_source"],
                    "shares_source": book["shares_source"],
                },
            )
            stats[METRIC_PB] += 1

        symbol = yahoo_symbol(company)
        if symbol is None:
            stats["skipped"]["sin_simbolo_yahoo"] += 1
            continue
        events = dividend_fetcher(symbol)
        if events is None:
            stats["skipped"]["dividendos_fuente_fallo"] += 1
            continue
        ttm, used = ttm_dividend_per_share(events, as_of)
        yahoo_yield = ttm / close
        finnhub_yield = finnhub_yield_fetcher(company.ticker)
        disagree = (
            finnhub_yield is not None
            and _rel_disagree(yahoo_yield, finnhub_yield) > DISAGREE_REL_TOL
        )
        status = STATUS_DISAGREE if disagree else STATUS_OK
        if disagree:
            stats["desacuerdo_fuentes"] += 1
        trace: dict[str, Any] = {
            "as_of": as_of.isoformat(),
            "ttm_dividend_per_share": str(ttm),
            "dividend_events": used,
            "price": str(close),
            "price_date": price_date.isoformat(),
            "yahoo_label": YAHOO_LABEL,
            "finnhub_label": FINNHUB_LABEL,
            "finnhub_yield_indicated": (
                str(finnhub_yield) if finnhub_yield is not None else None
            ),
            "desacuerdo_fuentes": disagree,
        }
        if yahoo_yield > EXTREME_YIELD:
            trace["yield_extremo_revisar"] = True
            stats["yield_extremo_revisar"] += 1
        _upsert_metric(
            db,
            tenant_id=tenant_id,
            company_id=company.id,
            metric=METRIC_YIELD,
            value=yahoo_yield,
            as_of=as_of,
            status=status,
            formula=(
                f"sum(dividendos/accion ex-fecha en (as_of-365d, as_of]) / close; "
                f"fuente: {YAHOO_LABEL}; contraste: {FINNHUB_LABEL}"
            ),
            trace=trace,
        )
        stats[METRIC_YIELD] += 1
    db.flush()
    return stats


def refresh_valuation_metrics(
    db: Session,
    *,
    as_of: date | None = None,
    dividend_fetcher: DividendFetcher | None = None,
    finnhub_yield_fetcher: FinnhubYieldFetcher | None = None,
) -> dict[str, Any]:
    """Job diario: metricas de valoracion de TODO el universo del tenant.

    Corre tras los cierres oficiales (22:30 UTC) para usar el close del dia.
    Cada dividendo es 1 peticion yfinance por ticker: mismo coste que los
    backfills diarios por ticker ya existentes (perfil Finnhub).
    """
    as_of = as_of or date.today()
    # Company es universo global (no TenantOwnedMixin), como en
    # sync_official_closes: el tenant acota las metricas escritas, no el universo.
    companies = list(db.scalars(select(Company).order_by(Company.ticker)).all())
    stats = compute_valuation_metrics(
        db,
        companies,
        as_of=as_of,
        dividend_fetcher=dividend_fetcher,
        finnhub_yield_fetcher=finnhub_yield_fetcher,
    )
    db.commit()
    return {"as_of": as_of.isoformat(), "companies": len(companies), **stats}
