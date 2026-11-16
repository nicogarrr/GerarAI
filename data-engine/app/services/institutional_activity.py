"""SELECT-only activity over the stored, CUSIP-linked 13F snapshot.

No provider calls, refresh, denominator inference or background work on GET.
Older snapshots lack a complete manager universe and must say sin_detalle.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.public_market_data import PublicFinancialFact
from app.services import institutional_holders as ih
from app.services.connectors.form13f_dataset import filing_index_url

FILTERS = frozenset({"all", "aumenta", "reduce", "nuevo", "vende_todo"})


def institutional_activity(db: Session, ticker: str, *, status: str = "all", page: int = 1,
                           page_size: int = 25) -> dict[str, Any] | None:
    """Stable magnitude/CIK ordering; NULL means filing missing, not zero shares."""
    if status not in FILTERS or page < 1 or not 1 <= page_size <= 100:
        raise ValueError("invalid activity pagination or status")
    snap = ih.linked_cusip_snapshot(db, ticker, provider=ih.PROVIDER)
    if snap is None:
        return None
    out: dict[str, Any] = {
        "ticker": snap.company.ticker, "cusip": snap.cusip, "identity_source": snap.identity,
        "status": snap.status or "sin_detalle", "reason": snap.reason, "period": None,
        "prior_period": None, "fetched_at": None, "filter": status, "page": page,
        "page_size": page_size, "total": None, "pages": None, "rows": [],
        "value_basis": "Reported USD value at quarter end, not purchases, sales or cash flow.",
        "company_ownership_pct_basis": None,
    }
    doc = snap.doc
    if doc is None:
        return out
    out["period"] = date.fromisoformat(doc.listing_key.split(":")[1]).isoformat()
    out["fetched_at"] = doc.fetched_at.isoformat()
    out["source_url"] = doc.source_url
    facts = list(db.scalars(select(PublicFinancialFact).where(
        PublicFinancialFact.source_document_id == doc.id).order_by(PublicFinancialFact.id)))
    if not any(f.metric == "13f.count.activity_detail_version" and f.value == 1 for f in facts):
        return out
    groups: dict[str, dict[str, PublicFinancialFact]] = {}
    for f in facts:
        if f.concept_name == ih.TOTAL:
            if f.metric == "13f.total.shares" and f.period_end.isoformat() != out["period"]:
                out["prior_period"] = f.period_end.isoformat()
            continue
        if "activity_role:all" in (f.derived_from_refs or []):
            groups.setdefault(f.concept_name, {})[f.metric] = f
    rows = []
    for concept, fields in groups.items():
        cur = fields.get("13f.holder.shares")
        prev = fields.get("13f.holder.prev_shares")
        value = fields.get("13f.holder.value_usd")
        tags = cur.derived_from_refs if cur else []
        state = next((t.split(":", 1)[1] for t in tags if t.startswith("status:")), "")
        if status != "all" and state != status:
            continue
        cik, _, name = concept.partition("|")
        current = float(cur.value) if cur and cur.accession else None
        previous = float(prev.value) if prev and prev.accession else None
        change = current - previous if current is not None and previous is not None else None
        rows.append({
            "cik": cik, "name": name, "status": state, "shares": current, "prev_shares": previous,
            "change": change, "change_pct": change / previous * 100 if change is not None and previous else None,
            "reported_value_usd": float(value.value) if value is not None else None,
            "company_ownership_pct": None,
            "filed": cur.filed.isoformat() if cur and cur.filed else None,
            "filing_url": filing_index_url(cik, cur.accession) if cur and cur.accession else None,
            "prev_filing_url": filing_index_url(cik, prev.accession) if prev and prev.accession else None,
        })
    rows.sort(key=lambda r: (r["change"] is None, -abs(r["change"] or 0), r["cik"]))
    total = len(rows)
    out.update(status="ok", total=total, pages=(total + page_size - 1) // page_size,
               rows=rows[(page - 1) * page_size:page * page_size])
    return out
