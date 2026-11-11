"""Read-only batch view of existing valuations and annual source-backed health."""
from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.tenancy import tenant_filters
from app.models import Company, FinancialFact, FundamentalModelVersion, FundamentalValuationSnapshot
from app.services.fair_value_service import resolve_fair_values
from app.services.financial_health import HealthFact, calculate_health
from app.valuation.cash_burn_base_rate import cash_burn_base_rate, latest_fiscal_year_values

HEALTH_METRICS = {
    "net_income", "total_assets", "operating_cash_flow", "long_term_debt",
    "current_assets", "current_liabilities", "common_stock_issued", "gross_profit",
    "revenue", "retained_earnings", "income_before_tax", "interest_expense",
    "total_equity", "total_liabilities",
}
SOURCE_ORDER = {"SEC": 0, "ESEF": 0, "CNMV": 0, "FMP": 1, "YAHOO_FUNDAMENTALS": 2}


def _number(raw: Any) -> float | None:
    try:
        val = float(raw)
    except (ValueError, TypeError, OverflowError):
        return None
    return val if isfinite(val) else None


def _reverse_base_rate_check(company: Company, facts: list[HealthFact], reverse: object,
                             growth: float | None, *, db: Session | None = None,
                             today: date | None = None) -> dict | None:
    """¿Con qué frecuencia lo consiguieron? % de empresas comparables (tamaño, crecimiento previo y
    sector, primera cifra publicada en la SEC) cuyos ingresos crecieron al menos lo que exige el
    precio en el mismo plazo del DCF inverso. Sin plazo guardado o sin ese plazo en la tabla: None.

    Los tramos de tamaño están en dólares: ingresos en UNA otra divisa se clasifican con el tipo
    oficial del cierre de su último ejercicio (``usd_size_fx``, de ``fx_rates``); sin ``db``, sin
    ese tipo o con varias divisas, el check es N/D con el motivo."""
    if growth is None or not isinstance(reverse, dict):
        return None
    horizon = (reverse.get("trace") or {}).get("horizon_years") if isinstance(reverse.get("trace"), dict) else None
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
        return None
    from app.services.estimate_base_rates import (
        SizeFx,
        for_annual_revenue,
        sector_of_cik,
        share_reaching,
        table_horizons,
        usd_size_fx,
    )

    measured = table_horizons()
    if horizon not in measured:
        # El TCAC a 6 años no es el de 5 ni el de 7: sin ese plazo medido, N/D con el motivo (no se interpola).
        plazos = ", ".join(str(h) for h in measured[:-1]) + (f" y {measured[-1]}" if len(measured) > 1 else
                                                               str(measured[0]) if measured else "")
        return {"share": None, "horizon_years": horizon,
                "reason": (f"la tasa base mide plazos de {plazos} años y el DCF inverso usa {horizon}: "
                           f"no se compara un plazo distinto") if measured else "tasa base sin plazos medidos"}
    from app.valuation.currency import fact_currency

    revenue = [f for f in facts if f.metric == "revenue" and f.value and f.value > 0]
    if not revenue:
        return None
    currencies = {fact_currency(f.unit) for f in revenue}
    if len(currencies) != 1 or None in currencies:
        return {"share": None, "reason": "ingresos en varias divisas o sin divisa: los tramos de tamaño de la "
                                         "tasa base están en dólares"}
    currency = next(iter(currencies))
    annual = {f.year: f.value for f in revenue}
    if currency == "USD":
        fx = SizeFx("USD", 1.0)
    elif db is None:
        fx = SizeFx(currency or "?", None, reason="ingresos en otra divisa: los tramos de tamaño de la tasa base "
                                                  "están en dólares")
    else:
        close = max(revenue, key=lambda f: (f.year, f.period_end)).period_end
        fx = usd_size_fx(db, currency, close, today=today or date.today())
    if fx.rate is None:
        return {"share": None, "reason": fx.reason}
    reach = share_reaching(for_annual_revenue(annual, sector=sector_of_cik(getattr(company, "cik", None)),
                                              horizon=horizon, usd_rate=fx.rate, size_note=fx.note), growth)
    if reach is None:
        return None
    return reach.as_dict(implied_formula=f"el precio exige {growth:+.1%}/año de ingresos durante {horizon} años "
                                         f"(DCF inverso)")


def _sic_sector(company: Company) -> str | None:
    """División SIC de la SEC del emisor (tabla de tasas base, sin red); None sin CIK o sin tabla."""
    from app.services.estimate_base_rates import sector_of_cik

    try:
        return sector_of_cik(getattr(company, "cik", None))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def build_summaries(db: Session, companies: list[Company], *, today: date | None = None) -> dict[str, dict]:
    today = today or date.today()
    if not companies:
        return {}
    ids = [c.id for c in companies]
    readings = resolve_fair_values(db, companies, today=today)
    rows = db.scalars(select(FinancialFact).options(selectinload(FinancialFact.source)).where(
        FinancialFact.company_id.in_(ids), FinancialFact.metric.in_(HEALTH_METRICS),
        FinancialFact.fiscal_year >= today.year - 5,
        *tenant_filters(db, FinancialFact),
    )).all()
    # Source priority, then most recently published restatement (not ingestion order).
    selected: dict[tuple, tuple[tuple, HealthFact]] = {}
    for row in rows:
        if row.fiscal_quarter != "FY" or row.fiscal_year is None or not row.is_reported or row.is_adjusted:
            continue
        if row.source_type not in SOURCE_ORDER or not row.source_url or (row.source and row.source.tenant_id != row.tenant_id):
            continue
        try:
            end = date.fromisoformat(row.period.split(":")[0])
        except ValueError:
            continue
        if end > today or (row.filed and row.filed > today):
            continue
        val = _number(row.value)
        if val is None:
            continue
        key = (row.company_id, row.metric, row.fiscal_year)
        rank = (SOURCE_ORDER[row.source_type], -(row.filed or date.min).toordinal(), -row.id)
        if key not in selected or rank < selected[key][0]:
            selected[key] = (rank, HealthFact(row.id, row.metric, row.fiscal_year, val,
                row.unit, end, row.source_url, row.source_type, row.source_id))
    ranked_models = select(
        FundamentalModelVersion.id,
        func.row_number().over(partition_by=FundamentalModelVersion.company_id,
            order_by=FundamentalModelVersion.version.desc()).label("rank"),
    ).where(FundamentalModelVersion.company_id.in_(ids),
        *tenant_filters(db, FundamentalModelVersion)).subquery()
    # Never revive an old publishable model when the newest one is blocked.
    snapshots = db.scalars(select(FundamentalValuationSnapshot)
        .join(FundamentalModelVersion, FundamentalModelVersion.id == FundamentalValuationSnapshot.model_version_id)
        .join(ranked_models, ranked_models.c.id == FundamentalModelVersion.id)
        .where(ranked_models.c.rank == 1, FundamentalModelVersion.publishable.is_(True),
            FundamentalValuationSnapshot.company_id.in_(ids),
            *tenant_filters(db, FundamentalModelVersion, FundamentalValuationSnapshot))
        .order_by(FundamentalValuationSnapshot.created_at.desc(), FundamentalValuationSnapshot.id.desc())).all()
    latest = {}
    for snapshot in snapshots:
        latest.setdefault(snapshot.company_id, snapshot)
    out = {}
    for company in companies:
        reading = readings[company.id]
        snapshot = latest.get(company.id)
        reverse = (snapshot.snapshot or {}).get("reverse_dcf") if snapshot else None
        growth = _number(reverse.get("required_revenue_growth")) if isinstance(reverse, dict) and reverse.get("status") == "ok" else None
        # El motivo del «No evaluable» viaja con el resumen: no es lo mismo
        # «faltan datos» (insufficient_data) que «el precio queda fuera de
        # todo escenario valorable» (out_of_bounds, AMZN 2026-11-03). Un
        # «No evaluable» sin motivo parece un fallo de la app.
        reverse_reason = None
        if growth is None and isinstance(reverse, dict):
            rev_status = reverse.get("status")
            if rev_status == "out_of_bounds":
                reverse_reason = ("El precio de mercado queda fuera de todo escenario "
                    "que el modelo puede valorar con el margen FCF actual; "
                    "hace falta un método acorde al tipo de empresa.")
            elif rev_status == "insufficient_data":
                missing = [str(m) for m in (reverse.get("missing_inputs") or []) if m]
                reverse_reason = ("Faltan datos para el DCF inverso: " + ", ".join(missing)) if missing else None
        # This is a separately dated model scenario, never the chosen thesis's claim.
        reverse_summary = {"status": "ok" if growth is not None else "not_evaluable",
            "required_revenue_growth": growth,
            "as_of": snapshot.created_at.isoformat() if snapshot and growth is not None else None,
            "source": "Modelo fundamental persistido",
            "model_version_id": snapshot.model_version_id if snapshot else None,
            "market_price": _number(snapshot.current_price) if snapshot else None,
            "reason": reverse_reason}
        company_facts = [entry[1] for key, entry in selected.items() if key[0] == company.id]
        reverse_summary["base_rate_check"] = _reverse_base_rate_check(company, company_facts, reverse, growth,
                                                                       db=db, today=today)
        out[company.ticker.upper()] = {
            "ticker": company.ticker.upper(), "fair_value": reading,
            "margin_convention": "discount_to_value_v1",
            "reverse_dcf": reverse_summary,
            "health": calculate_health(company_facts, sector=company.sector,
                company_type=company.company_type, today=today, industry=getattr(company, "industry", None),
                sic_sector=_sic_sector(company)),
            # Empresa que quema caja: de dónde parte (tasas base medidas), sin tocar la cifra.
            "base_rate": cash_burn_base_rate(latest_fiscal_year_values(company_facts), reading),
        }
    return out
