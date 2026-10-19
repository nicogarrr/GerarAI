"""Free SEC refresh primitive. Caller owns queue, dedupe and user-facing state."""
import re
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


_US_EXCHANGE_RE = re.compile(
    r"\b(?:NASDAQ(?:GS|GM|CM)?|NEW YORK STOCK EXCHANGE|NYSE(?:ARCA)?|AMEX|ARCA)\b"
)


def sec_eligible(company: Company) -> bool:
    """Identidad SEC verificable: CIK propio o ticker USD en bolsa US.

    Sin esta guarda un ticker europeo pelado (SAN, COV) resolveria en el
    registro US a su gemelo homonimo y contaminaria los fundamentales. La
    usa tanto el refresco por demanda como el backfill programado para no
    encolar jamas una compania que no pueda tener hechos SEC."""
    # Do not send a bare European ticker to the US registry as its US namesake.
    return bool(company.cik) or (
        company.currency == "USD" and bool(_US_EXCHANGE_RE.search(company.exchange.upper()))
    )


async def refresh_free_financials(db: Session, company: Company, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    previous = last_sec_refresh(db, company)
    base = {"provider": "SEC", "last_refreshed_at": previous.isoformat() if previous else None, "facts_imported": 0}
    if not sec_eligible(company):
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
