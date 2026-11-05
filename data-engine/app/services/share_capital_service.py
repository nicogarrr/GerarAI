"""Reported share balances and capital flows. Never attribute a net change to buybacks."""
from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, CorporateAction, Document, FinancialFact

CAPITAL_METRICS = {
    "shares_outstanding": "shares",
    "shares_repurchased": "shares",
    "common_stock_repurchased": "USD",
    "common_stock_issued": "USD",
    "stock_based_compensation": "USD",
}


# Saltos que un balance sin ajustar no puede explicar con recompras/emisiones normales:
# casi seguro un split (o fusion/IPO) no registrado. Se suprime la comparacion.
ABRUPT_UP_PCT = 40.0
ABRUPT_DOWN_PCT = -30.0


def _https_url(value: str | None) -> str | None:
    try:
        parsed = urlsplit(value or "")
        return value if parsed.scheme == "https" and parsed.hostname else None
    except ValueError:
        return None


def build_share_capital(db: Session, company: Company) -> dict[str, Any]:
    """FY cash flows are kept separate from point-in-time shares and quarterly YTD."""
    rows = db.scalars(
        select(FinancialFact)
        .options(selectinload(FinancialFact.source).load_only(
            Document.source_url, Document.published_at, Document.metadata_,
        ))
        .where(FinancialFact.company_id == company.id, FinancialFact.metric.in_(CAPITAL_METRICS))
        .order_by(FinancialFact.id.desc())
    ).all()
    balances: dict[str, dict[str, Any]] = {}
    flows: dict[str, dict[str, Any]] = {}
    for fact in rows:
        doc = fact.source
        if doc is None:
            continue
        # Unreported estimates, seeds, wrong units and untraceable values are not evidence.
        url = _https_url(doc.source_url)
        if (not fact.is_reported or fact.source_type not in {"SEC", "ESEF", "CNMV"}
                or fact.unit != CAPITAL_METRICS[fact.metric] or not url):
            continue
        try:
            end = date.fromisoformat(fact.period.split(":")[0])
        except ValueError:
            continue
        if end > date.today() or not fact.value.is_finite():
            continue
        if fact.metric == "shares_outstanding" and fact.value <= 0:
            continue
        meta = doc.metadata_ or {}
        period_metadata = (meta.get("capital_fact_provenance") or {}).get(fact.metric, {})
        provenance = period_metadata.get(fact.period) or {}
        reported_on = provenance.get("filed")
        evidence = {
            "value": float(fact.value), "unit": fact.unit, "date": end.isoformat(),
            "fact_id": fact.id, "source": fact.source_type, "source_url": url,
            "reported_on": reported_on,
            "source_updated_on": doc.published_at.date().isoformat() if doc.published_at else None,
            "status": "OFICIAL", "concept": provenance.get("concept"),
        }
        if fact.metric == "shares_outstanding":
            balances.setdefault(end.isoformat(), evidence)
        # No quarterly cash-flow aggregation: YTD and standalone quarters are not interchangeable.
        elif fact.fiscal_quarter == "FY" and fact.period.endswith(":FY"):
            flows.setdefault(end.isoformat(), {}).setdefault(fact.metric, evidence)
    splits = list(db.scalars(select(CorporateAction).where(
        CorporateAction.company_id == company.id,
        CorporateAction.action_type.in_(["split", "reverse_split"]),
    )))
    series = []
    previous = None
    for end, balance in sorted(balances.items()):
        events = [s for s in splits if previous and previous["date"] < s.effective_date.isoformat() <= end]
        delta = None
        percent = None
        abrupt = False
        if previous and not events:
            delta = balance["value"] - previous["value"]
            percent = delta / previous["value"] * 100
            if percent >= ABRUPT_UP_PCT or percent <= ABRUPT_DOWN_PCT:
                # Split no registrado en CorporateAction: no se presenta como cambio real.
                abrupt = True
                delta = None
                percent = None
        series.append({
            **balance, "previous_date": previous["date"] if previous else None,
            "net_change": delta, "net_change_pct": percent,
            "change_status": "DERIVADO" if percent is not None else "SIN_DATOS",
            "split_between_dates": bool(events),
            "abrupt_jump": abrupt,
        })
        previous = balance
    return {
        "ticker": company.ticker,
        "status": "OFICIAL" if series or flows else "SIN_DATOS",
        "as_of": date.today().isoformat(), "share_basis": "reported_unadjusted",
        "series": series,
        "annual_flows": [{"date": end, **values} for end, values in sorted(flows.items())],
    }
