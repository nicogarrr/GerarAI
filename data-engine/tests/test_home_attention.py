"""The inbox is grounded in unresolved thesis reviews, never price moves."""
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Position, ResearchReview, ThesisChange, WatchItem
from app.services.home_attention_service import pending_thesis_changes


def test_attention_tenant_status_membership_and_deduplication():
    engine = create_engine("sqlite://")
    tables = [Company.__table__, Position.__table__, ResearchReview.__table__, ThesisChange.__table__, WatchItem.__table__]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine) as db:
        company = Company(id=1, ticker="ASTS", name="AST", exchange="NASDAQ", company_type="equity", valuation_model="dcf")
        other = Company(id=2, ticker="OTHER", name="Other", exchange="NASDAQ", company_type="equity", valuation_model="dcf")
        db.add_all([company, other, WatchItem(tenant_id=1, symbol="ASTS")])
        db.add_all([
            ThesisChange(id=i, tenant_id=tenant, company_id=cid, summary=f"Change {i}", created_at=datetime(2026, 10, i, tzinfo=UTC))
            for i, tenant, cid in [(1,1,1),(2,1,1),(3,1,2),(4,2,1),(5,1,1)]
        ])
        db.add_all([
            ResearchReview(tenant_id=tenant, company_id=cid, thesis_change_id=change, status=status, review_type="thesis", title="Review")
            for tenant, cid, change, status in [(1,1,1,"open"),(1,1,1,"in_progress"),(1,1,2,"resolved"),(1,2,3,"open"),(2,1,4,"open"),(2,1,5,"open")]
        ])
        db.flush()
        db.info["tenant_id"] = 1
        rows = pending_thesis_changes(db)
        assert [r["id"] for r in rows] == [1]  # no duplicates, resolved, unfollowed or cross-tenant
        assert rows[0]["symbol"] == "ASTS"
        db.add(Position(tenant_id=1, company_id=2, quantity=2))
        db.flush()
        assert [r["id"] for r in pending_thesis_changes(db)] == [3, 1]
        assert [r["id"] for r in pending_thesis_changes(db, limit=1)] == [3]
        for position in db.query(Position).all():
            position.quantity = 0
        db.flush()
        assert [r["id"] for r in pending_thesis_changes(db)] == [1]
    engine.dispose()
