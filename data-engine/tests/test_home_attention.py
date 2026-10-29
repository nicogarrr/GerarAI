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


def test_attention_summary_uses_cached_headline_translation():
    """La tarjeta de Inicio no mezcla plantilla ES con titular crudo EN cuando
    el evento origen ya tiene traducción cacheada (auditoría 29-oct-2026)."""
    from app.models import NewsEvent
    from app.services.news_headline_translation import fingerprint

    engine = create_engine("sqlite://")
    tables = [Company.__table__, Position.__table__, ResearchReview.__table__, ThesisChange.__table__, WatchItem.__table__, NewsEvent.__table__]
    Base.metadata.create_all(engine, tables=tables)
    headline = "META One Big Reason Meta Stock Could Be a Winner Through 2030"
    translated = "Una gran razón por la que Meta podría ser ganadora hasta 2030"
    with Session(engine) as db:
        db.add(Company(id=1, ticker="META", name="Meta", exchange="NASDAQ", company_type="equity", valuation_model="dcf"))
        db.add(WatchItem(tenant_id=1, symbol="META"))
        db.add(NewsEvent(
            id=1, tenant_id=1, company_id=1, title=headline, source="manual",
            metadata_={"headline_translation": {
                "fingerprint": fingerprint(headline), "status": "translated", "text": translated}},
        ))
        db.add(ThesisChange(
            id=10, tenant_id=1, company_id=1,
            summary=f"Noticia material que requiere revisión de la tesis: {headline}. Refuerza la tesis.",
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
        ))
        db.add(ResearchReview(
            tenant_id=1, company_id=1, thesis_change_id=10, news_event_id=1,
            status="open", review_type="thesis", title="Review",
        ))
        db.flush()
        db.info["tenant_id"] = 1
        row = pending_thesis_changes(db)[0]
        assert translated in row["summary"]
        assert headline not in row["summary"]
    engine.dispose()


def test_attention_summary_untouched_without_translation_or_verbatim_match():
    """Sin traducción cacheada válida, o si el titular no aparece verbatim en
    el summary, el texto se devuelve tal cual: nunca se reescribe."""
    from app.models import NewsEvent
    from app.services.news_headline_translation import fingerprint

    engine = create_engine("sqlite://")
    tables = [Company.__table__, Position.__table__, ResearchReview.__table__, ThesisChange.__table__, WatchItem.__table__, NewsEvent.__table__]
    Base.metadata.create_all(engine, tables=tables)
    headline = "AST SpaceMobile Announces Third Quarter 2026 Results Date"
    with Session(engine) as db:
        db.add(Company(id=1, ticker="ASTS", name="AST", exchange="NASDAQ", company_type="equity", valuation_model="dcf"))
        db.add(WatchItem(tenant_id=1, symbol="ASTS"))
        # Sin traducción cacheada.
        db.add(NewsEvent(id=1, tenant_id=1, company_id=1, title=headline, source="manual", metadata_={}))
        # Traducción cacheada, pero el summary del cambio no incrusta el titular.
        db.add(NewsEvent(
            id=2, tenant_id=1, company_id=1, title=headline, source="manual",
            metadata_={"headline_translation": {
                "fingerprint": fingerprint(headline), "status": "translated", "text": "AST anuncia la fecha de resultados"}},
        ))
        summary_plain = f"Noticia material que requiere revisión de la tesis: {headline}. Dato nuevo."
        summary_other = "La evidencia automática clasificó la afirmación como contradictoria."
        db.add(ThesisChange(id=10, tenant_id=1, company_id=1, summary=summary_plain, created_at=datetime(2026, 10, 1, tzinfo=UTC)))
        db.add(ThesisChange(id=11, tenant_id=1, company_id=1, summary=summary_other, created_at=datetime(2026, 10, 2, tzinfo=UTC)))
        db.add(ResearchReview(tenant_id=1, company_id=1, thesis_change_id=10, news_event_id=1, status="open", review_type="thesis", title="R1"))
        db.add(ResearchReview(tenant_id=1, company_id=1, thesis_change_id=11, news_event_id=2, status="open", review_type="thesis", title="R2"))
        db.flush()
        db.info["tenant_id"] = 1
        rows = {row["id"]: row["summary"] for row in pending_thesis_changes(db)}
        assert rows[10] == summary_plain
        assert rows[11] == summary_other
    engine.dispose()
