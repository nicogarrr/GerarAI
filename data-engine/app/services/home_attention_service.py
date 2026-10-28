"""Read-only home inbox: actual thesis changes with an unresolved review."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Company, Position, ResearchReview, ThesisChange, WatchItem


def pending_thesis_changes(db: Session, limit: int = 100) -> list[dict]:
    watched = select(WatchItem.symbol).where(*tenant_filters(db, WatchItem))
    held = select(Position.company_id).where(Position.quantity > 0, *tenant_filters(db, Position))
    # EXISTS keeps several open reviews of one change from duplicating the item.
    unresolved = select(ResearchReview.id).where(
        ResearchReview.thesis_change_id == ThesisChange.id,
        ResearchReview.company_id == ThesisChange.company_id,
        ResearchReview.status.in_(["open", "in_progress"]),
        *tenant_filters(db, ResearchReview),
    ).exists()
    rows = db.execute(
        select(ThesisChange, Company.ticker)
        .join(Company, Company.id == ThesisChange.company_id)
        .where(
            Company.ticker.in_(watched) | Company.id.in_(held),
            unresolved,
            *tenant_filters(db, ThesisChange),
        )
        .order_by(ThesisChange.created_at.desc(), ThesisChange.id.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return [{
        "id": change.id,
        "symbol": ticker,
        "summary": change.summary,
        "direction": change.impact_direction,
        "createdAt": change.created_at.isoformat(),
    } for change, ticker in rows]
