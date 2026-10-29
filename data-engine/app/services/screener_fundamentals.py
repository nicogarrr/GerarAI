"""Sourced screener ratios from stored daily closes and financial facts.

Never pair financial statements across fiscal years, never mix currencies,
and never turn missing, seed or unverified inputs into apparent signals.
Ratios are computed from SEC/ESEF facts plus the latest stored daily close;
missing inputs stay null (honest "sin datos"), never fabricated.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from math import isfinite

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, FinancialFact, MarketPrice
from app.services.esef_fact_quarantine import fact_quarantine_reason
from app.services.price_units import close_in_company_currency
from app.services.split_adjustment import (
    cumulative_split_factor_after,
    period_end_date,
    split_events_by_company,
)

_METRICS = {"eps_diluted", "total_equity", "shares_diluted", "net_income"}
# QA inicio DCF: la tarjeta de oportunidades del inicio prueba candidatas del
# screener con /api/valuation/{ticker}; sin fundamentales persistidos el DCF
# no es calculable y la tarjeta quedaba «0 de 6 calculables». Se marca por
# fila si hay revenue y acciones diluidas (los dos inputs estrictamente
# necesarios del DCF estándar) para que la UI priorice esas candidatas.
_DCF_READINESS_METRICS = {"revenue"}
_TRUSTED_SOURCES = {"SEC", "ESEF"}
_PRICE_MAX_AGE_DAYS = 7  # weekends/holidays around the latest trading day
_FACT_MAX_AGE_YEARS = 2


def _ratio(value: Decimal | None) -> float | None:
    if value is None or not value.is_finite():
        return None
    number = float(value)
    return round(number, 4) if isfinite(number) else None


def _unit_currency(unit: str | None) -> str:
    """Normalize 'USD', 'iso4217:EUR' and 'iso4217:EUR/xbrli:shares' to 'USD'/'EUR'."""
    text = (unit or "").upper().strip()
    if text.startswith("ISO4217:"):
        text = text[len("ISO4217:"):]
    return text.split("/", 1)[0].strip()


def load_screener_ratios(
    db: Session,
    symbols: set[str],
    *,
    today: date | None = None,
    live_prices: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Bulk-load pe/pb/roe without N+1 queries. Missing/stale inputs stay null.

    Each ratio uses one complete annual snapshot (same fiscal year, same
    filing family): PE = close / diluted EPS, PB = close / (equity / shares),
    ROE = net income / equity * 100. Currency must match the company's quote
    currency; negative EPS or equity yields a null ratio, not a fake number.

    live_prices: cotizacion en vivo por ticker ({"price": float, "source":
    str, "as_of": str|None}). Gana sobre el MarketPrice local cuando su
    fecha es al menos tan reciente (con refrescos de universo a menor
    cadencia, un spot local de hace horas no compone ratios habiendo quote
    de hoy); sin fecha comparable gana el local fechado. La procedencia del
    ratio refleja la fuente usada.
    """
    if not symbols:
        return {}
    today = today or date.today()
    normalized = {symbol.upper() for symbol in symbols}
    companies = list(db.scalars(select(Company).where(Company.ticker.in_(normalized))))
    ids = [row.id for row in companies]
    if not ids:
        return {}
    prices = db.scalars(
        select(MarketPrice)
        .where(MarketPrice.company_id.in_(ids), MarketPrice.date >= today - timedelta(days=_PRICE_MAX_AGE_DAYS), MarketPrice.date <= today)
        .order_by(MarketPrice.date.desc(), MarketPrice.id.desc())
    ).all()
    facts = db.scalars(
        select(FinancialFact).options(selectinload(FinancialFact.source))
        .where(
            FinancialFact.company_id.in_(ids),
            FinancialFact.tenant_id == db.info.get("tenant_id"),
            FinancialFact.metric.in_(_METRICS | _DCF_READINESS_METRICS),
            FinancialFact.fiscal_year >= today.year - _FACT_MAX_AGE_YEARS,
            FinancialFact.source_type.in_(_TRUSTED_SOURCES),
            FinancialFact.is_reported.is_(True),
            or_(FinancialFact.fiscal_quarter.is_(None), FinancialFact.fiscal_quarter == 'FY'),
        )
        .order_by(FinancialFact.fiscal_year.desc(), FinancialFact.created_at.desc(), FinancialFact.id.desc())
    ).all()
    latest_price: dict[int, MarketPrice] = {}
    for row in prices:
        if row.company_id not in latest_price and row.source.lower() not in {"seed", "mock", "test"} and row.close and row.close > 0:
            latest_price[row.company_id] = row
    splits_by_company = split_events_by_company(db, ids)
    by_company: dict[int, dict[tuple[int, str], FinancialFact]] = {}
    for fact in facts:
        if fact_quarantine_reason(fact):
            continue
        # La ingesta SEC/ESEF guarda el periodo como "<end>:FY" (p.ej.
        # "2025-09-27:FY"); "FY"/"ANNUAL" a pelo es la forma legada.
        period = (fact.period or "").upper()
        if (
            period not in {"FY", "ANNUAL"}
            and not period.endswith((":FY", ":ANNUAL"))
        ) or fact.fiscal_year is None:
            continue
        by_company.setdefault(fact.company_id, {}).setdefault((fact.fiscal_year, fact.metric), fact)

    output: dict[str, dict] = {}
    live_prices = live_prices or {}
    for company in companies:
        price = latest_price.get(company.id)
        metrics: dict = {"pe": None, "pb": None, "roe": None}
        # QA inicio DCF: la tarjeta de oportunidades prioriza candidatas con
        # fundamentales persistidos (revenue y acciones diluidas, inputs
        # estrictamente necesarios del DCF estándar); se declara aunque no
        # haya precio para que la sonda elija bien sus candidatas.
        facts_for_company = by_company.get(company.id, {})
        metric_names = {metric for _, metric in facts_for_company}
        metrics["has_fundamentals"] = {"revenue", "shares_diluted"} <= metric_names
        live = live_prices.get(company.ticker.upper())
        live_close: Decimal | None = None
        live_date: date | None = None
        if live is not None:
            try:
                live_close = Decimal(str(live.get("price") or ""))
            except (InvalidOperation, ValueError):
                live_close = None
            if live_close is not None and live_close <= 0:
                live_close = None
            live_as_of = live.get("as_of")
            if live_as_of:
                try:
                    live_date = date.fromisoformat(str(live_as_of)[:10])
                except ValueError:
                    live_date = None
        # La quote en vivo gana cuando es al menos tan reciente que el
        # MarketPrice local; sin fecha en vivo comparable, gana el local
        # fechado. Sin fila local, la live sirve como antes (fallback).
        use_live = live_close is not None and (
            price is None or (live_date is not None and live_date >= price.date)
        )
        if price is None and not use_live:
            output[company.ticker.upper()] = metrics
            continue
        if use_live:
            close = live_close
        else:
            # Cierre cotizado en otra divisa que las cuentas (SHEL.L en GBp,
            # cuentas en USD): FX point-in-time a la divisa de la compania;
            # sin tipo, ratios nulos (nunca peniques contra EPS en USD).
            close = close_in_company_currency(
                db, Decimal(str(price.close)), quote_currency=price.quote_currency,
                company=company, on=price.date,
            )
            if close is None:
                output[company.ticker.upper()] = metrics
                continue
        price_provenance = (
            {"source": live.get("source") or "live", "date": live.get("as_of"), "id": None}
            if use_live
            else {"source": price.source, "date": price.date.isoformat(), "id": price.id}
        )
        currency = (company.currency or "").upper()
        years = sorted({year for year, _ in facts_for_company}, reverse=True)
        provenance = {"price": price_provenance, "facts": {}}

        def pair(left: str, right: str):
            for year in years:
                a = facts_for_company.get((year, left))
                b = facts_for_company.get((year, right))
                if a and b and a.value is not None and b.value is not None and b.value > 0:
                    return a, b
            return None

        for year in years:
            eps = facts_for_company.get((year, "eps_diluted"))
            if eps and eps.value and eps.value > 0 and _unit_currency(eps.unit) == currency:
                # El precio es de HOY: si hubo split tras el cierre del
                # ejercicio del EPS, el EPS se expresa en acciones actuales
                # (reportado / factor acumulado) o el PER sale inflado por
                # el factor del split.
                split_factor = cumulative_split_factor_after(
                    splits_by_company.get(company.id, []),
                    period_end_date(eps.period),
                )
                metrics["pe"] = _ratio(close / (eps.value / split_factor))
                pe_prov: dict = {"id": eps.id, "source": eps.source_type, "year": year}
                if split_factor != 1:
                    pe_prov["split_factor"] = format(split_factor.normalize(), "f")
                    pe_prov["calculation"] = (
                        "close / (eps_diluted / cumulative_split_factor)"
                    )
                provenance["facts"]["pe"] = pe_prov
                break
        equity_shares = pair("total_equity", "shares_diluted")
        if equity_shares:
            equity, shares = equity_shares
            if equity.value > 0 and _unit_currency(equity.unit) == currency and (shares.unit or "").lower() == "shares":
                # Mismo ajuste que el PER: el precio es de HOY y las acciones
                # son del cierre del ejercicio. Tras un split posterior el
                # recuento se expresa en acciones actuales (x factor
                # acumulado); sin ajuste el P/B salia dividido por el factor.
                shares_split_factor = cumulative_split_factor_after(
                    splits_by_company.get(company.id, []),
                    period_end_date(shares.period),
                )
                metrics["pb"] = _ratio(
                    close / (equity.value / (shares.value * shares_split_factor))
                )
                pb_prov: dict = {"ids": [equity.id, shares.id], "sources": [equity.source_type, shares.source_type], "year": equity.fiscal_year}
                if shares_split_factor != 1:
                    pb_prov["split_factor"] = format(shares_split_factor.normalize(), "f")
                    pb_prov["calculation"] = (
                        "close / (total_equity / (shares_diluted * cumulative_split_factor))"
                    )
                provenance["facts"]["pb"] = pb_prov
        income_equity = pair("net_income", "total_equity")
        if income_equity:
            income, equity = income_equity
            if _unit_currency(income.unit) == currency and _unit_currency(equity.unit) == currency:
                metrics["roe"] = _ratio(income.value / equity.value * 100)
                provenance["facts"]["roe"] = {"ids": [income.id, equity.id], "sources": [income.source_type, equity.source_type], "year": income.fiscal_year}
        if provenance["facts"]:
            metrics["ratioProvenance"] = provenance
        output[company.ticker.upper()] = metrics
    return output
