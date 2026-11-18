"""Un evento factual y no alertante por aviso Form 144 (tenant/accession).

Espejo de ``schedule13dg_news``: el aviso queda visible en Noticias como
hecho regulatorio primario. Un Form 144 es un aviso de venta PROPUESTA:
el titulo y el resumen lo dicen siempre; nunca se redacta como venta
ejecutada ni como senal direccional.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.entities import Company, NewsEvent

_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_ARCHIVE = re.compile(r"^https://(?:www\.)?sec\.gov/Archives/edgar/data/0*(\d+)/(\d{18})/")


def ensure_news(db, filing: dict, parsed: dict | None = None, *, tenant_id=None, _retry=False) -> dict:
    accession = str(filing.get("accession_number") or "")
    ticker = str(filing.get("issuer_ticker") or "").strip().upper()
    source_url = str(filing.get("document_url") or "")
    archive = _ARCHIVE.match(source_url)
    if not _ACCESSION.fullmatch(accession) or not ticker or not archive:
        return {"created": False, "reason": "invalid_identity"}
    if archive.group(2) != accession.replace("-", ""):
        return {"created": False, "reason": "invalid_identity"}
    issuer = (parsed or {}).get("issuer_cik")
    if issuer and str(issuer).lstrip("0") != archive.group(1).lstrip("0"):
        return {"created": False, "reason": "issuer_mismatch"}
    try:
        filing_date = datetime.fromisoformat(str(filing.get("filing_date") or "")).replace(tzinfo=UTC)
    except ValueError:
        return {"created": False, "reason": "invalid_date"}
    scope = tenant_id if tenant_id is not None else db.info.get("tenant_id")
    predicate = NewsEvent.tenant_id.is_(None) if scope is None else NewsEvent.tenant_id == scope
    identity = f"{scope if scope is not None else 'legacy'}:{accession}"
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None or (company.cik and int(company.cik) != int(archive.group(1))):
        return {"created": False, "reason": "issuer_not_found"}
    row = db.scalar(select(NewsEvent).where(predicate, NewsEvent.sec_filing_identity == identity))
    if row is None:
        # Adopt legacy SEC events from before the accession identity column.
        candidates = db.scalars(select(NewsEvent).where(predicate, NewsEvent.company_id == company.id, NewsEvent.source == "SEC"))
        row = next((r for r in candidates if (m := _ARCHIVE.match(r.url or "")) and m.group(2) == archive.group(2)), None)
    created = row is None
    try:
        with db.begin_nested():
            if row is None:
                row = NewsEvent(tenant_id=scope, company_id=company.id, date=filing_date, source="SEC", url=source_url)
                db.add(row)
            row.sec_filing_identity = identity
            data = dict(parsed or {})
            metadata = dict(row.metadata_ or {})
            previous = metadata.get("proposed_sale") or {}
            if not data or (previous.get("parsed_ok") and not data.get("parsed_ok")):
                data = previous
            form = str(filing.get("form") or "144")
            seller = data.get("seller_name")
            row.title = (f"Aviso de venta propuesta (Form {form})" + (f": {seller}" if seller else ""))[:500]
            row.summary = "Aviso ante la SEC de una venta propuesta; no acredita una venta ejecutada."
            totals = data.get("totals") or {}
            if totals.get("shares_to_sell") is not None:
                row.summary += f" Acciones que se proponen vender: {totals['shares_to_sell']:,.0f}."
            if totals.get("aggregate_market_value") is not None:
                row.summary += f" Importe de mercado declarado: {totals['aggregate_market_value']:,.0f} USD."
            if totals.get("approx_sale_date"):
                row.summary += f" Fecha aproximada declarada: {totals['approx_sale_date']}."
            plan_dates = data.get("plan_adoption_dates") or []
            if plan_dates:
                row.summary += f" Bajo plan 10b5-1 adoptado el {plan_dates[0]}."
            row.event_type = "insider_proposed_sale"
            # Editorial rule, not an SEC fact or a directional investment signal.
            row.materiality_score = 5
            row.impact_direction = "neutral"
            row.affected_thesis = False
            row.requires_update = False
            row.affected_assumptions = []
            metadata.update({"connector": "sec", "headline_from_source": False,
                             "accession_number": accession, "proposed_sale": data,
                             "materiality_policy": "5/10: aviso regulatorio de venta propuesta; relevancia informativa, no una venta ejecutada",
                             "no_new_alerts": True,
                             "assessment": {"source_tier": "tier_primary", "source_trust_score": 1.0,
                                 "materiality_reasons": ["5/10: aviso regulatorio de venta propuesta; relevancia informativa, no una venta ejecutada"],
                                 "source_policy": "SEC primaria; venta propuesta declarada, no operacion ejecutada",
                                 "model_route": "deterministic_insider_proposed_sale"}})
            row.metadata_ = metadata
            db.flush()
    except IntegrityError:
        # Only retry a unique identity race, never hide another constraint error.
        winner = db.scalar(select(NewsEvent).where(predicate, NewsEvent.sec_filing_identity == identity))
        if _retry or winner is None:
            raise
        return ensure_news(db, filing, parsed, tenant_id=scope, _retry=True)
    return {"created": created, "event_id": row.id}
