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
        # This is a separately dated model scenario, never the chosen thesis's claim.
        reverse_summary = {"status": "ok" if growth is not None else "not_evaluable",
            "required_revenue_growth": growth,
            "as_of": snapshot.created_at.isoformat() if snapshot and growth is not None else None,
            "source": "Modelo fundamental persistido",
            "model_version_id": snapshot.model_version_id if snapshot else None,
            "market_price": _number(snapshot.current_price) if snapshot else None}
        out[company.ticker.upper()] = {
            "ticker": company.ticker.upper(), "fair_value": reading,
            "margin_convention": "discount_to_value_v1",
            "reverse_dcf": reverse_summary,
            "health": calculate_health([entry[1] for key, entry in selected.items()
                if key[0] == company.id], sector=company.sector, company_type=company.company_type, today=today),
        }
    return out
