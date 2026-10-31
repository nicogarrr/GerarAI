"""Una pasada por relacion: GET /api/alerts y /api/attention-thesis no gastan
un round-trip por tabla relacionada. Los conteos fijan la forma; si alguien
reintroduce una consulta secuencial, el test falla."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.alerts import list_alerts
from app.models.entities import (
    AlertDelivery,
    Base,
    Company,
    NewsEvent,
    ResearchAlert,
    ResearchReview,
    ThesisChange,
    WatchItem,
)
from app.services.home_attention_service import pending_thesis_changes


class _QueryCounter:
    def __init__(self, engine):
        self.count = 0
        event.listen(engine, "before_cursor_execute", self._inc)

    def _inc(self, *args):
        self.count += 1

    def reset(self):
        self.count = 0


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def test_list_alerts_loads_relations_in_bounded_queries():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "t1"
        now = datetime.now(UTC)
        company = _company(db, "AAPL")
        event = NewsEvent(
            tenant_id="t1", company_id=company.id, title="H", url="https://example.com/1",
            date=now - timedelta(days=1), source="src", metadata_={},
        )
        db.add(event)
        db.flush()
        alerts = [
            ResearchAlert(tenant_id="t1", company_id=company.id, alert_type="price_above",
                          severity="high", title="t1", message="m", fingerprint="fp-1",
                          channels=["in_app"], status="open", metadata_={}),
            ResearchAlert(tenant_id="t1", company_id=company.id, alert_type="tracked_news",
                          severity="medium", title="t2", message="m", fingerprint="fp-2",
                          channels=["in_app"], status="open",
                          metadata_={"news_event_id": event.id}),
        ]
        db.add_all(alerts)
        db.flush()
        for alert in alerts:
            db.add(AlertDelivery(tenant_id="t1", alert_id=alert.id, channel="in_app", status="sent"))
        db.commit()
        counter = _QueryCounter(engine)
        rows = list_alerts(ticker=None, status=None, include_snoozed=False, limit=100, db=db)
        assert len(rows) == 2
        assert rows[0].ticker in {"AAPL", None}
        # alerts + companies (IN aparte) + news events + deliveries = 4:
        # forma medida mas rapida en el A/B del piloto (31-oct, restore PG):
        # el join de company en el listado dio p50 25,4 -> 27,9/26,3 ms
        # (~4-10 % peor). Si vuelve el join (3), el test falla.
        assert counter.count == 4
    engine.dispose()


def test_attention_bridge_and_event_in_one_query():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "t1"
        now = datetime.now(UTC)
        company = _company(db, "ASTS")
        db.add(WatchItem(tenant_id="t1", symbol="ASTS"))
        event = NewsEvent(
            tenant_id="t1", company_id=company.id, title="H", url="https://example.com/2",
            date=now - timedelta(days=1), source="src", metadata_={},
        )
        db.add(event)
        db.flush()
        change = ThesisChange(tenant_id="t1", company_id=company.id, summary="Cambio",
                              impact_direction="up", created_at=now)
        db.add(change)
        db.flush()
        db.add(ResearchReview(tenant_id="t1", company_id=company.id, thesis_change_id=change.id,
                              news_event_id=event.id, status="open",
                              review_type="thesis_change", title="r"))
        db.commit()
        counter = _QueryCounter(engine)
        rows = pending_thesis_changes(db, limit=100)
        assert [row["id"] for row in rows] == [change.id]
        # cambios (join company) + puente review->evento (join) = 2; el
        # puente en dos consultas secuenciales (3) es la regresión que se fija.
        assert counter.count == 2
    engine.dispose()
