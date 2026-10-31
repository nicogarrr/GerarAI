"""Overlay de calidad del radar ProPicks+DCA (datos de tenant, en tiempo de lectura).

NUNCA se persiste en los snapshots públicos de precio: el embudo ProPicks y
los fundamentales son datos del tenant. Se calcula por petición para las
empresas listadas y alimenta el filtro ``quality=clear`` y la marca por fila.

Regla quality-v1 (propicks_dca_radar.quality_checks): un input ausente nunca
pasa. Liquidez = mediana de close*volume de las últimas 20 sesiones con datos;
``market_cap`` solo cuenta en USD (la política exige cap>=1B USD: otra divisa
se declara ausente antes que convertir con un tipo de cambio no verificado).
"""

from __future__ import annotations

from datetime import date
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import (
    CalculatedMetric,
    Company,
    FinancialFact,
    MarketPrice,
    ProPickCandidate,
    ProPickRun,
)
from app.services.propicks_dca_radar import quality_checks
from app.services.propicks_funnel_service import LEVERAGE_METRIC
from app.valuation.currency import _ticker_suffix, listing_quote_unit, normalize_currency, SUFFIX_QUOTE_UNIT
from app.valuation.financial_snapshot import _period_type

FCF_METRIC = "free_cash_flow"
MARKET_CAP_METRIC = "market_cap"
LIQUIDITY_SESSIONS = 20


def _latest_run_id(db: Session) -> int | None:
    return db.scalar(
        select(ProPickRun.id)
        .where(ProPickRun.status == "completed", *tenant_filters(db, ProPickRun))
        .order_by(ProPickRun.as_of.desc())
        .limit(1)
    )


def _funnel_passed(db: Session, run_id: int | None) -> set[int]:
    if run_id is None:
        return set()
    return set(db.scalars(
        select(ProPickCandidate.company_id)
        .where(ProPickCandidate.run_id == run_id, ProPickCandidate.passed.is_(True))
    ).all())


def _latest_metric_values(db: Session, company_ids: list[int], metric: str) -> dict[int, float]:
    if not company_ids:
        return {}
    latest_period = (
        select(
            CalculatedMetric.company_id.label("company_id"),
            func.max(CalculatedMetric.period).label("max_period"),
        )
        .where(
            CalculatedMetric.company_id.in_(company_ids),
            CalculatedMetric.metric == metric,
            *tenant_filters(db, CalculatedMetric),
        )
        .group_by(CalculatedMetric.company_id)
        .subquery()
    )
    rows = db.execute(
        select(CalculatedMetric.company_id, CalculatedMetric.value).join(
            latest_period,
            (CalculatedMetric.company_id == latest_period.c.company_id)
            & (CalculatedMetric.period == latest_period.c.max_period),
        ).where(CalculatedMetric.metric == metric, *tenant_filters(db, CalculatedMetric))
    ).all()
    return {int(cid): float(value) for cid, value in rows if value is not None}


def _fcf_pairs(db: Session, company_ids: list[int]) -> dict[int, tuple[float, float, bool]]:
    """Dos últimos años fiscales con FCF; comparables = misma unidad y años seguidos."""
    if not company_ids:
        return {}
    rows = db.scalars(
        select(FinancialFact)
        .where(
            FinancialFact.company_id.in_(company_ids),
            FinancialFact.metric == FCF_METRIC,
            FinancialFact.fiscal_year.is_not(None),
            *tenant_filters(db, FinancialFact),
        )
        .order_by(FinancialFact.company_id, FinancialFact.fiscal_year.desc(), FinancialFact.id.desc())
    ).all()
    by_company: dict[int, list[FinancialFact]] = {}
    for fact in rows:
        # Solo ejercicios fiscales completos: un Q3 con fiscal_year relleno
        # NO es comparable con un FY (misma clasificacion que el snapshot:
        # acepta FY/ANNUAL y filas legadas sin trimestre con periodo anual).
        if _period_type(fact.period, fact.fiscal_quarter) != "FY":
            continue
        facts = by_company.setdefault(fact.company_id, [])
        if not any(f.fiscal_year == fact.fiscal_year for f in facts):
            facts.append(fact)
    out: dict[int, tuple[float, float, bool]] = {}
    for cid, facts in by_company.items():
        if len(facts) < 2:
            continue
        current, previous = facts[0], facts[1]
        comparable = (current.unit == previous.unit
                      and current.fiscal_year == (previous.fiscal_year or 0) + 1)
        out[cid] = (float(current.value), float(previous.value), comparable)
    return out


def _fundamentals_age_days(db: Session, company_ids: list[int], *, as_of: date) -> dict[int, int]:
    if not company_ids:
        return {}
    rows = db.execute(
        select(FinancialFact.company_id, func.max(FinancialFact.filed))
        .where(FinancialFact.company_id.in_(company_ids), *tenant_filters(db, FinancialFact))
        .group_by(FinancialFact.company_id)
    ).all()
    return {int(cid): (as_of - filed).days for cid, filed in rows if filed is not None}


def _liquidity(db: Session, company_ids: list[int]) -> dict[int, tuple[float | None, int]]:
    """Mediana de close*volume y nº de sesiones, sobre las últimas 20 con datos."""
    if not company_ids:
        return {}
    companies = {
        c.id: c for c in db.scalars(select(Company).where(Company.id.in_(company_ids)))
    }
    rows = db.execute(
        select(MarketPrice.company_id, MarketPrice.date, MarketPrice.close, MarketPrice.volume,
               MarketPrice.quote_currency)
        .where(
            MarketPrice.company_id.in_(company_ids),
            MarketPrice.close.is_not(None),
            MarketPrice.close > 0,
            MarketPrice.volume.is_not(None),
            MarketPrice.volume > 0,
        )
        # id desc: desempate determinista; con 2 proveedores en la misma
        # sesion se cuenta UNA (la de mayor id), no dos sesiones.
        .order_by(MarketPrice.company_id, MarketPrice.date.desc(), MarketPrice.id.desc())
    ).all()
    by_company: dict[int, list[float]] = {}
    seen_dates: dict[int, set] = {}
    for cid, day, close, volume, quote_currency in rows:
        cid = int(cid)
        # El umbral de quality-v1 esta en USD: solo cuentan sesiones con
        # unidad USD verificable. Un close en peniques o yenes multiplicado
        # por el volumen se leia como dolares y coronaba como liquida una
        # accion con una fraccion del umbral real. Filas legacy (NULL) solo
        # son compatibles si el listado es USD (contrato de price_units);
        # cualquier otra divisa se declara AUSENTE, como el market_cap,
        # antes que convertir con un tipo de cambio no verificado.
        unit = (quote_currency or "").strip().upper() or None
        if unit is None:
            # Fila legacy sin unidad: solo cuenta con USD VERIFICABLE, es
            # decir divisa USD declarada explicitamente en la ficha o un
            # sufijo de ticker cuya unidad conocida sea USD. NUNCA el default
            # USD de listing_currency: con la ficha vacia ese default
            # convertia una unidad desconocida en dolares (fail-open).
            company = companies.get(cid)
            if company is None or not _legacy_unit_is_verified_usd(
                company.ticker, company.currency
            ):
                continue
        elif unit != "USD":
            continue
        if day in seen_dates.setdefault(cid, set()):
            continue
        seen_dates[cid].add(day)
        dollars = by_company.setdefault(cid, [])
        if len(dollars) < LIQUIDITY_SESSIONS:
            dollars.append(float(close) * float(volume))
    return {cid: (median(dollars), len(dollars)) for cid, dollars in by_company.items()}


def _ticker_has_known_suffix(ticker: str | None) -> bool:
    suffix = _ticker_suffix(ticker or "")
    return bool(suffix and suffix in SUFFIX_QUOTE_UNIT)


def _legacy_unit_is_verified_usd(ticker: str | None, company_currency: str | None) -> bool:
    """Unidad legacy compatible con USD SOLO con evidencia explicita.

    Divisa declarada en la ficha que normaliza a USD, o sufijo del ticker
    cuya unidad conocida normalice a USD (hoy ninguno: el mapa solo cubre
    subunidades y divisas no-USD). ``listing_currency`` no sirve aqui: su
    fallback USD por omision no es evidencia de la unidad real.
    """
    declared_major, _ = normalize_currency(company_currency)
    if declared_major == "USD":
        return True
    suffix_major, _ = normalize_currency(listing_quote_unit(ticker, None))
    return suffix_major == "USD" and bool(_ticker_has_known_suffix(ticker))


def quality_for_companies(db: Session, company_ids: list[int], *, as_of: date) -> dict[int, dict]:
    """Veredicto quality-v1 por empresa; inputs ausentes nunca pasan."""
    if not company_ids:
        return {}
    companies = {c.id: c for c in db.scalars(select(Company).where(Company.id.in_(company_ids)))}
    passed = _funnel_passed(db, _latest_run_id(db))
    leverage = _latest_metric_values(db, company_ids, LEVERAGE_METRIC)
    market_caps = _latest_metric_values(db, company_ids, MARKET_CAP_METRIC)
    fcf = _fcf_pairs(db, company_ids)
    ages = _fundamentals_age_days(db, company_ids, as_of=as_of)
    liquidity = _liquidity(db, company_ids)

    out: dict[int, dict] = {}
    for cid in company_ids:
        company = companies.get(cid)
        if company is None:
            continue
        pair = fcf.get(cid)
        dollar_median, sessions = liquidity.get(cid, (None, 0))
        # La política exige cap>=1B USD: otra divisa se declara ausente antes
        # que convertir con un tipo de cambio no verificado.
        market_cap = market_caps.get(cid) if (company.currency or "").upper() == "USD" else None
        verdict = quality_checks(
            sector=company.sector or "",
            funnel_passed=cid in passed,
            leverage=leverage.get(cid),
            fcf_current=pair[0] if pair else None,
            fcf_previous=pair[1] if pair else None,
            periods_comparable=pair[2] if pair else False,
            fundamentals_age_days=ages.get(cid),
            median_dollar_volume=dollar_median,
            volume_sessions=sessions,
            market_cap_usd=market_cap,
        )
        verdict["market_cap_usd"] = market_cap
        out[cid] = verdict
    return out
