"""Cross-tenant regression for column/aggregate selects.

`with_loader_criteria` scopes ORM entity loads; a `select(Model.column)` or an
aggregate is a column query and must carry its own tenant predicate. These
tests seed the SAME global company (or separate ones) for two tenants and
assert each tenant only sees its own rows, both directions.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (register every table on Base.metadata)
from app.models import (
    CalculatedMetric,
    CashBalance,
    Company,
    CorporateAction,
    DividendRecord,
    Document,
    FinancialFact,
    InsiderFiling,
    InsiderTransaction,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeGraphNode,
    MarketPrice,
    NewsEvent,
    Position,
    ResearchReview,
    Tenant,
    ThesisChange,
    ThesisVersion,
    Transaction,
    WatchItem,
)
from app.models.entities import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _tenant(db: Session, external_id: str) -> Tenant:
    tenant = Tenant(external_id=external_id, name=external_id, metadata_={})
    db.add(tenant)
    db.commit()
    return tenant


def _company(db: Session, ticker: str, *, isin: str | None = None) -> Company:
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="TEST",
        currency="USD",
        sector="Tech",
        industry="Tech",
        company_type="standard",
        valuation_model="standard_dcf",
        isin=isin,
    )
    db.add(company)
    db.commit()
    return company


@pytest.fixture()
def two(db: Session):
    tenant_a = _tenant(db, "tenant-a")
    tenant_b = _tenant(db, "tenant-b")
    company_a = _company(db, "AAA", isin="US0000000001")
    company_b = _company(db, "BBB", isin="US0000000002")
    return db, tenant_a, tenant_b, company_a, company_b


def _as(db: Session, tenant: Tenant) -> None:
    db.info["tenant_id"] = tenant.id


def _thesis(db: Session, tenant: Tenant, company: Company, version: int, value: float) -> None:
    _as(db, tenant)
    db.add(
        ThesisVersion(
            company_id=company.id,
            version=version,
            status="published",
            thesis_markdown=f"v{version}",
            executive_summary=f"v{version}",
            expected_value=value,
            valuation_basis={},
        )
    )
    db.commit()


def test_thesis_tickers_only_lists_the_active_tenant(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    _thesis(db, tenant_a, company_a, 1, 10)
    _thesis(db, tenant_b, company_b, 1, 20)

    from app.api.routes.companies import thesis_tickers

    _as(db, tenant_a)
    assert thesis_tickers(db).tickers == ["AAA"]
    _as(db, tenant_b)
    assert thesis_tickers(db).tickers == ["BBB"]


def test_news_duplicate_detection_does_not_see_other_tenant_events(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    _as(db, tenant_b)
    db.add(
        NewsEvent(
            company_id=company_b.id,
            title="Same headline",
            url="https://example.test/same",
            source="feed",
            materiality_score=1,
        )
    )
    db.commit()

    from app.services.news_service import NewsService

    service = NewsService()
    _as(db, tenant_a)
    assert service._is_duplicate(db, company_a, "Same headline", "https://example.test/same") is False
    assert service._is_duplicate(db, company_a, "Same headline", None) is False

    _as(db, tenant_a)
    db.add(
        NewsEvent(
            company_id=company_a.id,
            title="Same headline",
            url="https://example.test/same",
            source="feed",
            materiality_score=1,
        )
    )
    db.commit()
    assert service._is_duplicate(db, company_a, "Same headline", "https://example.test/same") is True


def test_tax_declarant_partidas_only_include_the_active_tenant(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    _as(db, tenant_a)
    db.add(Position(company_id=company_a.id, quantity=1, base_currency="EUR"))
    db.add(CashBalance(currency="EUR", balance=10))
    db.commit()
    _as(db, tenant_b)
    db.add(Position(company_id=company_b.id, quantity=1, base_currency="USD"))
    db.add(CashBalance(currency="USD", balance=10))
    db.commit()

    from app.services.tax_declarant_service import partidas

    _as(db, tenant_a)
    assert partidas(db) == ["US0000000001", "cash:EUR"]
    _as(db, tenant_b)
    assert partidas(db) == ["US0000000002", "cash:USD"]


def test_company_changes_counts_and_review_bridge_are_tenant_scoped(two):
    db, tenant_a, tenant_b, company_a, _ = two
    since = datetime(2026, 1, 1, tzinfo=UTC)
    created = since + timedelta(days=1)

    _as(db, tenant_a)
    change_a = ThesisChange(
        company_id=company_a.id,
        summary="A change",
        impact_direction="positive",
        requires_review=True,
        created_at=created,
    )
    db.add_all(
        [
            Document(
                company_id=company_a.id,
                title="A doc",
                source_type="sec_filing",
                source_url="https://example.test/a",
                created_at=created,
            ),
            FinancialFact(
                company_id=company_a.id,
                metric="revenue",
                value=Decimal("1"),
                unit="USD",
                period="FY2025",
                created_at=created,
            ),
            change_a,
        ]
    )
    db.commit()

    _as(db, tenant_b)
    event_b = NewsEvent(
        company_id=company_a.id,
        title="B news",
        url="https://example.test/b",
        source="feed",
        materiality_score=1,
        created_at=created,
    )
    change_b = ThesisChange(
        company_id=company_a.id,
        summary="B change",
        impact_direction="negative",
        requires_review=False,
        created_at=created,
    )
    db.add_all(
        [
            Document(
                company_id=company_a.id,
                title="B doc",
                source_type="sec_filing",
                source_url="https://example.test/b",
                created_at=created,
            ),
            FinancialFact(
                company_id=company_a.id,
                metric="ebitda",
                value=Decimal("2"),
                unit="USD",
                period="FY2025",
                created_at=created,
            ),
            event_b,
            change_b,
        ]
    )
    db.flush()
    db.add_all(
        [
            ResearchReview(
                company_id=company_a.id,
                review_type="news",
                title="B review of A change",
                thesis_change_id=change_a.id,
                news_event_id=event_b.id,
            ),
            ResearchReview(
                company_id=company_a.id,
                review_type="news",
                title="B review of B change",
                thesis_change_id=change_b.id,
                news_event_id=event_b.id,
            ),
        ]
    )
    db.commit()

    from app.services.company_changes_service import changes_since

    _as(db, tenant_a)
    out_a = changes_since(db, company_a.id, since)
    assert out_a["documentos"]["total"] == 1
    assert [d["titulo"] for d in out_a["documentos"]["items"]] == ["A doc"]
    assert out_a["hechos"]["total"] == 1
    assert {(m["metric"], m["n"]) for m in out_a["hechos"]["por_metrica"]} == {("revenue", 1)}
    assert [c["resumen"] for c in out_a["cambios_tesis"]] == ["A change"]
    assert out_a["cambios_tesis"][0]["fuente_url"] is None

    _as(db, tenant_b)
    out_b = changes_since(db, company_a.id, since)
    assert out_b["documentos"]["total"] == 1
    assert [d["titulo"] for d in out_b["documentos"]["items"]] == ["B doc"]
    assert out_b["hechos"]["total"] == 1
    assert {(m["metric"], m["n"]) for m in out_b["hechos"]["por_metrica"]} == {("ebitda", 1)}
    assert [c["resumen"] for c in out_b["cambios_tesis"]] == ["B change"]
    assert out_b["cambios_tesis"][0]["fuente_url"] == "https://example.test/b"


def test_screener_metric_coverage_is_tenant_scoped(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    _as(db, tenant_a)
    db.add_all(
        [
            CalculatedMetric(
                company_id=company_a.id,
                metric="roe",
                value=Decimal("2"),
                period="FY2025",
                status="ok",
                formula="x",
            ),
            FinancialFact(
                company_id=company_a.id,
                metric="revenue",
                value=Decimal("1"),
                unit="USD",
                period="FY2025",
            ),
        ]
    )
    db.commit()
    _as(db, tenant_b)
    db.add_all(
        [
            CalculatedMetric(
                company_id=company_b.id,
                metric="roce",
                value=Decimal("2"),
                period="FY2025",
                status="ok",
                formula="x",
            ),
            FinancialFact(
                company_id=company_b.id,
                metric="ebitda",
                value=Decimal("2"),
                unit="USD",
                period="FY2025",
            ),
        ]
    )
    db.commit()

    from app.services.screener_service import ScreenerService

    _as(db, tenant_a)
    assert ScreenerService().metric_coverage(db) == ["revenue", "roe"]
    _as(db, tenant_b)
    assert ScreenerService().metric_coverage(db) == ["ebitda", "roce"]


def test_corporate_actions_dividends_and_sync_status_are_tenant_scoped(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    now = datetime.now(UTC)
    today = date.today()

    _as(db, tenant_a)
    db.add_all(
        [
            Position(company_id=company_a.id, quantity=1, base_currency="EUR"),
            DividendRecord(
                company_id=company_a.id,
                ex_date=today,
                amount=Decimal("1"),
                currency="USD",
                source="test",
                fetched_at=now,
            ),
            CorporateAction(
                company_id=company_a.id,
                action_type="split",
                effective_date=today,
                ratio=Decimal("2"),
                fetched_at=now,
            ),
        ]
    )
    db.commit()

    _as(db, tenant_b)
    db.add_all(
        [
            Position(company_id=company_b.id, quantity=1, base_currency="EUR"),
            DividendRecord(
                company_id=company_b.id,
                ex_date=today,
                amount=Decimal("2"),
                currency="USD",
                source="test",
                fetched_at=now + timedelta(days=1),
            ),
            CorporateAction(
                company_id=company_b.id,
                action_type="split",
                effective_date=today,
                ratio=Decimal("3"),
                fetched_at=now + timedelta(days=1),
            ),
        ]
    )
    db.commit()

    from app.api.routes.corporate_actions import _declared_dividends, sync_status

    _as(db, tenant_a)
    assert [row["ticker"] for row in _declared_dividends(db)] == ["AAA"]
    status_a = sync_status(db)
    assert datetime.fromisoformat(status_a["dividends_last_import"]).replace(
        tzinfo=None
    ) == now.replace(tzinfo=None)
    assert datetime.fromisoformat(status_a["splits_last_import"]).replace(
        tzinfo=None
    ) == now.replace(tzinfo=None)

    _as(db, tenant_b)
    assert [row["ticker"] for row in _declared_dividends(db)] == ["BBB"]
    status_b = sync_status(db)
    later = now + timedelta(days=1)
    assert datetime.fromisoformat(status_b["dividends_last_import"]).replace(
        tzinfo=None
    ) == later.replace(tzinfo=None)
    assert datetime.fromisoformat(status_b["splits_last_import"]).replace(
        tzinfo=None
    ) == later.replace(tzinfo=None)


def test_watchlist_monitor_uses_only_the_active_tenants_thesis(two, monkeypatch):
    db, tenant_a, tenant_b, company_a, _ = two
    db.add(
        MarketPrice(
            company_id=company_a.id,
            date=date.today(),
            open=10,
            high=10,
            low=10,
            close=10,
        )
    )
    db.commit()
    _thesis(db, tenant_a, company_a, 1, 10)
    _thesis(db, tenant_b, company_a, 2, 20)

    async def _no_earnings(*args, **kwargs):
        return {"status": "ok", "events": []}

    monkeypatch.setattr("app.api.routes.watchlist.fetch_earnings_range", _no_earnings)

    from app.api.routes.watchlist import watchlist_monitor

    _as(db, tenant_a)
    body_a = asyncio.run(watchlist_monitor(tickers="AAA", db=db))
    assert body_a["items"]["AAA"]["fair_value"] == 10.0

    _as(db, tenant_b)
    body_b = asyncio.run(watchlist_monitor(tickers="AAA", db=db))
    assert body_b["items"]["AAA"]["fair_value"] == 20.0


def test_dividend_sync_uses_only_the_active_tenants_positions_and_watchlist(two, monkeypatch):
    db, tenant_a, tenant_b, company_a, company_b = two
    _as(db, tenant_a)
    db.add_all(
        [
            Position(company_id=company_a.id, quantity=1, base_currency="EUR"),
            WatchItem(symbol="AAA"),
        ]
    )
    db.commit()
    _as(db, tenant_b)
    db.add_all(
        [
            Position(company_id=company_b.id, quantity=1, base_currency="EUR"),
            WatchItem(symbol="BBB"),
        ]
    )
    db.commit()

    from app.services.dividend_ingestion_service import DividendIngestionService

    seen: list[str] = []

    async def _fake_sync_company(self, db, *, ticker):
        seen.append(ticker)
        return {"ticker": ticker, "status": "ok", "inserted": 0, "existing": 0}

    monkeypatch.setattr(DividendIngestionService, "sync_company", _fake_sync_company)
    service = DividendIngestionService()

    _as(db, tenant_a)
    asyncio.run(service.sync_portfolio(db))
    assert seen == ["AAA"]

    seen.clear()
    _as(db, tenant_b)
    asyncio.run(service.sync_portfolio(db))
    assert seen == ["BBB"]


def test_short_position_alert_requires_the_active_tenants_tracking(two, monkeypatch):
    db, tenant_a, tenant_b, company_a, _ = two
    _as(db, tenant_a)
    db.add(Position(company_id=company_a.id, quantity=1, base_currency="EUR"))
    db.commit()

    from app.services import short_positions_service as service
    from app.services.review_alert_service import ReviewAlertService

    emitted: list[int] = []

    def _emit(self, db, *, company_id, **kwargs):
        emitted.append(company_id)
        return None

    monkeypatch.setattr(ReviewAlertService, "emit_alert", _emit)
    now = datetime.now(UTC)
    payload = {
        "short_interest": {
            "settlement_date": now.date().isoformat(),
            "previous_short_interest": 100,
            "short_interest": 200,
            "source_url": "https://example.test/shorts",
        }
    }

    _as(db, tenant_a)
    service.emit_shorts_increase(db, company_a, {}, payload, now)
    assert emitted == [company_a.id]

    emitted.clear()
    _as(db, tenant_b)
    service.emit_shorts_increase(db, company_a, {}, payload, now)
    assert emitted == []


