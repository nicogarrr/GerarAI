"""Free SEC refresh primitive. Caller owns queue, dedupe and user-facing state."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, Document, FinancialFact
from app.services.financial_ingestion_service import FinancialIngestionService


def last_sec_refresh(db: Session, company: Company) -> datetime | None:
    doc = db.scalar(select(Document).where(
        Document.company_id == company.id, Document.source_type == "SEC",
        Document.title == f"SEC XBRL facts - {company.ticker.upper()}",
    ))
    raw = (doc.metadata_ or {}).get("last_refreshed_at") if doc else None
    try:
        value = datetime.fromisoformat(raw) if isinstance(raw, str) else None
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value
    except ValueError:
        return None


async def refresh_free_financials(db: Session, company: Company, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    previous = last_sec_refresh(db, company)
    base = {"provider": "SEC", "last_refreshed_at": previous.isoformat() if previous else None, "facts_imported": 0}
    # Do not send a bare European ticker to the US registry as its US namesake.
    us_exchange = company.exchange.upper() in {"NASDAQ", "NYSE", "AMEX", "NYSEARCA", "NYSE AMERICAN", "NASDAQGS", "NASDAQGM", "NASDAQCM"}
    if not company.cik and not (company.currency == "USD" and us_exchange):
        return {**base, "status": "skipped", "reason": "emisor_no_sec"}
    stored = int(db.scalar(select(func.count(FinancialFact.id)).where(
        FinancialFact.company_id == company.id, FinancialFact.source_type == "SEC",
    )) or 0)
    if previous and timedelta(0) <= now - previous < timedelta(hours=24) and stored:
        return {**base, "status": "skipped", "reason": "actualizado_ultimas_24h"}
    try:
        result = await FinancialIngestionService().refresh_from_sec(db=db, company=company)
        # Refresh can add zero new facts when the stored history is unchanged.
        count = int(db.scalar(select(func.count(FinancialFact.id)).where(
            FinancialFact.company_id == company.id, FinancialFact.source_type == "SEC",
        )) or 0)
        if not count:
            return {**base, "status": "error", "reason": "sin_hechos_financieros"}
        timestamp = last_sec_refresh(db, company)
        return {**base, "status": "ok", "last_refreshed_at": timestamp.isoformat() if timestamp else None,
                "facts_imported": int(result.get("facts_imported", 0))}
    except Exception:
        db.rollback()
        # Never return provider exception strings (may contain private URLs).
        return {**base, "status": "error", "reason": "sec_no_disponible"}
