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
    FundamentalModelVersion,
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
    # Tesis publicada: su valor justo exige el modelo publicable vigente del
    # mismo tenant (puerta de publicación, fail-closed).
    db.add(
        FundamentalModelVersion(
            company_id=company.id, version=version, engine_version="test", algorithm_version="test",
            framework_key="dcf", horizon_years=10, status="ok", publishable=True,
            input_fingerprint=f"iso-{tenant.id}-{company.id}-{version}", forecast_fingerprint="forecast",
            market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
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


def test_propicks_funnel_reads_only_the_active_tenants_facts(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    _as(db, tenant_a)
    db.add_all(
        [
            CalculatedMetric(
                company_id=company_a.id,
                metric="roic",
                value=Decimal("1"),
                period="FY2025",
                status="ok",
                formula="x",
            ),
            FinancialFact(
                company_id=company_a.id,
                metric="net_income",
                value=Decimal("10"),
                unit="USD",
                period="FY2025",
                fiscal_year=2025,
                fiscal_quarter="FY",
            ),
            FinancialFact(
                company_id=company_a.id,
                metric="revenue",
                value=Decimal("5"),
                unit="USD",
                period="FY2023",
                fiscal_year=2023,
                fiscal_quarter="FY",
            ),
            FinancialFact(
                company_id=company_a.id,
                metric="revenue",
                value=Decimal("10"),
                unit="USD",
                period="FY2024",
                fiscal_year=2024,
                fiscal_quarter="FY",
            ),
            FinancialFact(
                company_id=company_a.id,
                metric="revenue",
                value=Decimal("20"),
                unit="USD",
                period="FY2025",
                fiscal_year=2025,
                fiscal_quarter="FY",
            ),
            FinancialFact(
                company_id=company_a.id,
                metric="free_cash_flow",
                value=Decimal("5"),
                unit="USD",
                period="FY2025",
                fiscal_year=2025,
                fiscal_quarter="FY",
            ),
            FinancialFact(
                company_id=company_a.id,
                metric="shares_diluted",
                value=Decimal("2"),
                unit="shares",
                period="FY2025",
                fiscal_year=2025,
                fiscal_quarter="FY",
            ),
        ]
    )
    db.commit()
    _as(db, tenant_b)
    db.add_all(
        [
            CalculatedMetric(
                company_id=company_b.id,
                metric="roe_5y",
                value=Decimal("2"),
                period="FY2025",
                status="ok",
                formula="x",
            ),
            FinancialFact(
                company_id=company_b.id,
                metric="net_income",
                value=Decimal("-10"),
                unit="USD",
                period="FY2025",
                fiscal_year=2025,
                fiscal_quarter="FY",
            ),
            FinancialFact(
                company_id=company_b.id,
                metric="revenue",
                value=Decimal("15"),
                unit="USD",
                period="FY2023",
                fiscal_year=2023,
                fiscal_quarter="FY",
            ),
            FinancialFact(
                company_id=company_b.id,
                metric="revenue",
                value=Decimal("30"),
                unit="USD",
                period="FY2024",
                fiscal_year=2024,
                fiscal_quarter="FY",
            ),
            FinancialFact(
                company_id=company_b.id,
                metric="revenue",
                value=Decimal("60"),
                unit="USD",
                period="FY2025",
                fiscal_year=2025,
                fiscal_quarter="FY",
            ),
            FinancialFact(
                company_id=company_b.id,
                metric="free_cash_flow",
                value=Decimal("6"),
                unit="USD",
                period="FY2025",
                fiscal_year=2025,
                fiscal_quarter="FY",
            ),
            FinancialFact(
                company_id=company_b.id,
                metric="shares_diluted",
                value=Decimal("3"),
                unit="shares",
                period="FY2025",
                fiscal_year=2025,
                fiscal_quarter="FY",
            ),
        ]
    )
    db.commit()

    from app.services import propicks_funnel_service as funnel
    from app.services import propicks_gems_service as gems

    _as(db, tenant_a)
    assert set(funnel._latest_metrics(db)) == {(company_a.id, "roic")}
    assert funnel._earnings_consistency(db) == {company_a.id: (1, 1)}
    assert set(funnel._revenue_cagr(db)) == {company_a.id}
    assert set(gems._latest_fcf_and_shares(db, 2024)) == {company_a.id}

    _as(db, tenant_b)
    assert set(funnel._latest_metrics(db)) == {(company_b.id, "roe_5y")}
    assert funnel._earnings_consistency(db) == {company_b.id: (0, 1)}
    assert set(funnel._revenue_cagr(db)) == {company_b.id}
    assert set(gems._latest_fcf_and_shares(db, 2024)) == {company_b.id}


def test_corporate_action_service_holding_and_first_trade_are_tenant_scoped(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    _as(db, tenant_a)
    db.add_all(
        [
            Position(company_id=company_a.id, quantity=1, base_currency="EUR"),
            Transaction(
                company_id=company_a.id,
                action="buy",
                quantity=1,
                price=1,
                trade_date=date(2024, 1, 1),
            ),
        ]
    )
    db.commit()
    _as(db, tenant_b)
    db.add_all(
        [
            Position(company_id=company_b.id, quantity=1, base_currency="EUR"),
            Transaction(
                company_id=company_b.id,
                action="buy",
                quantity=1,
                price=1,
                trade_date=date(2024, 2, 1),
            ),
        ]
    )
    db.commit()

    from app.services.corporate_actions_service import CorporateActionService

    service = CorporateActionService()
    ids = {company_a.id, company_b.id}

    _as(db, tenant_a)
    assert service.first_trade_dates(db, ids) == {company_a.id: date(2024, 1, 1)}
    assert service.companies_with_holding(db, ids) == {company_a.id}

    _as(db, tenant_b)
    assert service.first_trade_dates(db, ids) == {company_b.id: date(2024, 2, 1)}
    assert service.companies_with_holding(db, ids) == {company_b.id}


def test_insider_filings_and_feed_totals_are_tenant_scoped(two):
    db, tenant_a, tenant_b, _, _ = two
    today = date.today().isoformat()

    _as(db, tenant_a)
    filing_a = InsiderFiling(
        accession_number="0000000000-26-000001",
        form="4",
        issuer_cik="0000000001",
        issuer_ticker="AAA",
        filing_date=today,
        parser_version="test",
    )
    db.add(filing_a)
    db.flush()
    db.add(
        InsiderTransaction(
            fingerprint="a" * 64,
            filing_id=filing_a.id,
            accession_number=filing_a.accession_number,
            form="4",
            issuer_ticker="AAA",
            code="P",
            tx_date=today,
            shares=1,
            price=1,
            value=1,
        )
    )
    db.commit()

    _as(db, tenant_b)
    filing_b = InsiderFiling(
        accession_number="0000000000-26-000002",
        form="4",
        issuer_cik="0000000002",
        issuer_ticker="AAA",
        filing_date=today,
        parser_version="test",
    )
    db.add(filing_b)
    db.flush()
    db.add(
        InsiderTransaction(
            fingerprint="b" * 64,
            filing_id=filing_b.id,
            accession_number=filing_b.accession_number,
            form="4",
            issuer_ticker="AAA",
            code="P",
            tx_date=today,
            shares=1,
            price=1,
            value=1,
        )
    )
    db.commit()

    from app.api.routes.insider import insider_filings
    from app.services.insider_feed import build_feed

    _as(db, tenant_a)
    resp_a = insider_filings(ticker="AAA", limit=20, db=db)
    assert resp_a["total"] == 1
    # La LISTA (entity load, scoped por with_loader_criteria) tambien queda
    # aislada: antes solo el count (column select con tenant_filters) tenia
    # asercion, y la lista podia filtrar filings del otro tenant sin test.
    assert [f["accession_number"] for f in resp_a["filings"]] == ["0000000000-26-000001"]
    assert resp_a["filings"][0]["transaction_count"] == 1
    feed_a = build_feed(db, today=date.today())
    assert feed_a["totals"]["filings_total"] == 1
    assert feed_a["totals"]["filings_with_transactions"] == 1

    _as(db, tenant_b)
    resp_b = insider_filings(ticker="AAA", limit=20, db=db)
    assert resp_b["total"] == 1
    assert [f["accession_number"] for f in resp_b["filings"]] == ["0000000000-26-000002"]
    assert resp_b["filings"][0]["transaction_count"] == 1
    feed_b = build_feed(db, today=date.today())
    assert feed_b["totals"]["filings_total"] == 1
    assert feed_b["totals"]["filings_with_transactions"] == 1


def test_insider_filings_empty_for_tenant_without_rows(two):
    """A ingiere, B no ve nada: lista vacia, count 0, total 0 y FPI label None.

    Cubre las tres lecturas de /api/insider/filings de golpe: la lista
    (entity load), el total (count con tenant_filters) y _foreign_issuer
    (column select sobre Document.metadata). Sin aislamiento, B veria el
    filing de A y el estatus FPI derivado de los documentos SEC de A.
    """
    db, tenant_a, tenant_b, _, _ = two
    today = date.today().isoformat()
    fpia = _company(db, "FPIA")

    _as(db, tenant_a)
    db.add(
        InsiderFiling(
            accession_number="0000000000-26-000101",
            form="4",
            issuer_cik="0000000101",
            issuer_ticker="FPIA",
            filing_date=today,
            parser_version="test",
        )
    )
    db.add(
        Document(
            company_id=fpia.id,
            title="10-K FPIA",
            source_type="SEC",
            metadata_={"form": "10-K"},
        )
    )
    db.commit()

    from app.api.routes.insider import insider_filings

    _as(db, tenant_b)
    resp_b = insider_filings(ticker="FPIA", limit=20, db=db)
    assert resp_b["status"] == "ok"
    assert resp_b["filings"] == []
    assert resp_b["count"] == 0
    assert resp_b["total"] == 0
    assert resp_b["foreign_issuer"] is None

    _as(db, tenant_a)
    resp_a = insider_filings(ticker="FPIA", limit=20, db=db)
    assert [f["accession_number"] for f in resp_a["filings"]] == ["0000000000-26-000101"]
    assert resp_a["count"] == 1
    assert resp_a["total"] == 1
    assert resp_a["foreign_issuer"] is False


def test_propicks_radar_tracked_symbols_are_tenant_scoped(two):
    """_tracked_symbols mezcla dos column selects (WatchItem.symbol y
    Company.ticker via Position) con tenant_filters explicito: si cualquiera
    lo pierde, el radar de B marca como "seguidos" los simbolos de A."""
    db, tenant_a, tenant_b, company_a, _ = two

    _as(db, tenant_a)
    db.add(WatchItem(symbol="AAA"))
    db.add(Position(company_id=company_a.id, quantity=1))
    db.commit()

    from app.api.routes.propicks_radar import _tracked_symbols

    _as(db, tenant_b)
    assert "AAA" not in _tracked_symbols(db)

    _as(db, tenant_a)
    assert "AAA" in _tracked_symbols(db)


def test_earnings_and_catalyst_followed_companies_are_tenant_scoped(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    company_a.exchange = "NASDAQ"
    company_b.exchange = "NASDAQ"
    db.commit()

    _as(db, tenant_a)
    db.add_all(
        [
            Position(company_id=company_a.id, quantity=1, base_currency="USD"),
            WatchItem(symbol="AAA"),
        ]
    )
    db.commit()
    _as(db, tenant_b)
    db.add_all(
        [
            Position(company_id=company_b.id, quantity=1, base_currency="USD"),
            WatchItem(symbol="BBB"),
        ]
    )
    db.commit()

    from app.services.catalyst_calendar_service import held_tickers, watchlist_us_tickers
    from app.services.earnings_dates_service import followed_companies

    _as(db, tenant_a)
    assert set(followed_companies(db)) == {"AAA"}
    assert held_tickers(db)[0] == {"AAA"}
    assert watchlist_us_tickers(db, set()) == {"AAA"}

    _as(db, tenant_b)
    assert set(followed_companies(db)) == {"BBB"}
    assert held_tickers(db)[0] == {"BBB"}
    assert watchlist_us_tickers(db, set()) == {"BBB"}


def test_knowledge_document_chunk_count_is_tenant_scoped(two):
    db, tenant_a, tenant_b, _, _ = two

    _as(db, tenant_a)
    document_a = KnowledgeDocument(
        title="A doc",
        document_type="note",
        status="ready",
    )
    db.add(document_a)
    db.flush()
    db.add(
        KnowledgeChunk(
            knowledge_document_id=document_a.id,
            chunk_index=0,
            content="A chunk",
        )
    )
    db.commit()

    _as(db, tenant_b)
    db.add(
        KnowledgeChunk(
            knowledge_document_id=document_a.id,
            chunk_index=1,
            content="B chunk linked to A doc",
        )
    )
    db.commit()

    from app.services.knowledge_library_service import KnowledgeLibraryService

    _as(db, tenant_a)
    document = KnowledgeLibraryService.get_document(db, document_a.id)
    assert document is not None
    assert document["chunk_count"] == 1


def test_knowledge_graph_counts_are_tenant_scoped(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    _as(db, tenant_a)
    db.add(
        KnowledgeGraphNode(
            node_key="node:a",
            node_type="company",
            label="AAA",
            company_id=company_a.id,
        )
    )
    db.commit()
    _as(db, tenant_b)
    db.add(
        KnowledgeGraphNode(
            node_key="node:b",
            node_type="company",
            label="BBB",
            company_id=company_b.id,
        )
    )
    db.commit()

    from app.services.knowledge_graph_service import KnowledgeGraphService

    service = KnowledgeGraphService()
    _as(db, tenant_a)
    payload_a = service.graph(db)
    assert payload_a["total_node_count"] == 1
    assert [node["label"] for node in payload_a["nodes"]] == ["AAA"]

    _as(db, tenant_b)
    payload_b = service.graph(db)
    assert payload_b["total_node_count"] == 1
    assert [node["label"] for node in payload_b["nodes"]] == ["BBB"]


def test_bottleneck_discovery_quota_is_tenant_scoped(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    from app.models.bottleneck_discovery import BottleneckDiscovery
    from app.services.bottleneck_discovery_service import todays_discoveries

    now = datetime.now(UTC)
    today = now.date()
    _as(db, tenant_a)
    db.add(
        BottleneckDiscovery(
            theme="energy",
            ticker=company_a.ticker,
            reasoning="A",
            model="test",
            day=today,
            created_at=now,
        )
    )
    db.commit()
    _as(db, tenant_b)
    db.add(
        BottleneckDiscovery(
            theme="energy",
            ticker=company_b.ticker,
            reasoning="B",
            model="test",
            day=today,
            created_at=now,
        )
    )
    db.commit()

    _as(db, tenant_a)
    assert todays_discoveries(db, now) == 1
    _as(db, tenant_b)
    assert todays_discoveries(db, now) == 1


def test_llm_proposal_daily_count_is_tenant_scoped(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    from app.models.paper_trading import PaperTrade
    from app.services.llm_proposal_runner import todays_llm_proposals

    def _trade(company: Company) -> PaperTrade:
        return PaperTrade(
            proposal_key="llm:test",
            ticker=company.ticker,
            direction="long",
            horizon="1m",
            thesis="test",
            conviction=Decimal("0.5"),
            proposed_entry=Decimal("1"),
            stop=Decimal("0.9"),
            target=Decimal("1.1"),
            quantity=Decimal("1"),
            inference_basis="test",
        )

    now = datetime.now(UTC)
    _as(db, tenant_a)
    db.add(_trade(company_a))
    db.commit()
    _as(db, tenant_b)
    db.add(_trade(company_b))
    db.commit()

    _as(db, tenant_a)
    assert todays_llm_proposals(db, now) == 1
    _as(db, tenant_b)
    assert todays_llm_proposals(db, now) == 1


def test_propicks_price_run_lookup_is_tenant_scoped(two):
    db, tenant_a, tenant_b, company_a, company_b = two
    from app.models import ProPickCandidate, ProPickRun
    from app.services.propicks_price_service import latest_run_passed_companies

    now = datetime.now(UTC)
    _as(db, tenant_a)
    run_a = ProPickRun(as_of=now, status="completed", funnel_version="v1")
    db.add(run_a)
    db.flush()
    db.add(
        ProPickCandidate(
            run_id=run_a.id,
            company_id=company_a.id,
            passed=True,
            rank=1,
            score=1.0,
        )
    )
    db.commit()
    _as(db, tenant_b)
    run_b = ProPickRun(as_of=now, status="completed", funnel_version="v1")
    db.add(run_b)
    db.flush()
    db.add(
        ProPickCandidate(
            run_id=run_b.id,
            company_id=company_b.id,
            passed=True,
            rank=1,
            score=2.0,
        )
    )
    db.commit()

    _as(db, tenant_a)
    assert [company.ticker for company in latest_run_passed_companies(db)] == ["AAA"]
    _as(db, tenant_b)
    assert [company.ticker for company in latest_run_passed_companies(db)] == ["BBB"]


def test_split_sync_uses_only_the_active_tenants_positions(two, monkeypatch):
    db, tenant_a, tenant_b, company_a, company_b = two
    _as(db, tenant_a)
    db.add(Position(company_id=company_a.id, quantity=1, base_currency="EUR"))
    db.commit()
    _as(db, tenant_b)
    db.add(Position(company_id=company_b.id, quantity=1, base_currency="EUR"))
    db.commit()

    from app.services.split_ingestion_service import SplitIngestionService

    seen: list[str] = []

    async def _fake_sync_company(self, db, *, ticker):
        seen.append(ticker)
        return {"ticker": ticker, "status": "ok", "inserted": 0, "existing": 0}

    monkeypatch.setattr(SplitIngestionService, "sync_company", _fake_sync_company)
    service = SplitIngestionService()

    _as(db, tenant_a)
    asyncio.run(service.sync_portfolio(db))
    assert seen == ["AAA"]

    seen.clear()
    _as(db, tenant_b)
    asyncio.run(service.sync_portfolio(db))
    assert seen == ["BBB"]


def test_portfolio_ledger_held_quantity_is_tenant_scoped(two):
    db, tenant_a, tenant_b, company_a, _ = two
    _as(db, tenant_a)
    db.add(
        Transaction(
            company_id=company_a.id,
            action="buy",
            quantity=2,
            price=1,
            trade_date=date(2024, 1, 1),
        )
    )
    db.commit()
    _as(db, tenant_b)
    db.add(
        Transaction(
            company_id=company_a.id,
            action="buy",
            quantity=3,
            price=1,
            trade_date=date(2024, 1, 2),
        )
    )
    db.commit()

    from app.services.portfolio_ledger_service import PortfolioLedgerService

    service = PortfolioLedgerService()
    _as(db, tenant_a)
    assert service._held_quantity(db, company_a.id) == Decimal("2")
    _as(db, tenant_b)
    assert service._held_quantity(db, company_a.id) == Decimal("3")


def test_tenant_filters_fail_closed_when_context_is_required(db, monkeypatch):
    from types import SimpleNamespace

    from app.core.tenancy import tenant_filters

    monkeypatch.setattr(
        "app.core.tenancy.get_settings",
        lambda: SimpleNamespace(research_auth_required=True, is_production=False),
    )
    with pytest.raises(RuntimeError):
        tenant_filters(db, FinancialFact)

    db.info["tenant_id"] = 42
    assert len(tenant_filters(db, FinancialFact)) == 1


def test_loader_criteria_scopes_column_and_aggregate_selects_too(two):
    """Fija el comportamiento medido en SQLAlchemy 2.1.6 (rango fijado
    >=2.0.32,<2.2): el with_loader_criteria de app/core/database.py acota
    TAMBIEN los column selects, agregados, GROUP BY, joins, subqueries IN y
    window functions de modelos tenant-owned, no solo los entity loads.

    Si un bump de SQLAlchemy cambia este comportamiento, este test rompe CI
    y hay que re-auditar todas las lecturas que hoy llevan tenant_filters
    explicito como segunda capa. Los predicados explicitos siguen siendo
    obligatorios: defensa en profundidad, fail-closed sin contexto y
    ejecuciones no-ORM (db.connection()/text()), que nunca ven el criteria.
    """
    db, tenant_a, tenant_b, company_a, _ = two

    from sqlalchemy import func, select

    _as(db, tenant_a)
    db.add(WatchItem(symbol="AAA"))
    db.add(Position(company_id=company_a.id, quantity=1))
    db.commit()

    _as(db, tenant_b)
    # Column select (scalars y execute): acotado sin tenant_filters explicito.
    assert db.scalars(select(WatchItem.symbol)).all() == []
    assert db.execute(select(WatchItem.symbol)).all() == []
    # Agregados count y max: acotados.
    assert db.scalar(select(func.count()).select_from(WatchItem)) == 0
    assert db.scalar(select(func.max(WatchItem.id))) is None
    # GROUP BY multicolumna via db.execute: acotado.
    grouped = select(WatchItem.symbol, func.count()).group_by(WatchItem.symbol)
    assert db.execute(grouped).all() == []
    # Join y subquery IN sobre entidad tenant-owned: acotados.
    joined = (
        select(Company.ticker).join(Position, Position.company_id == Company.id).where(Position.quantity > 0)
    )
    assert db.scalars(joined).all() == []
    subquery = select(Company.ticker).where(
        Company.id.in_(select(Position.company_id).where(Position.quantity > 0))
    )
    assert db.scalars(subquery).all() == []
    # Window function: acotada.
    windowed = select(func.row_number().over(order_by=WatchItem.id)).select_from(WatchItem)
    assert db.scalars(windowed).all() == []

    _as(db, tenant_a)
    assert db.scalars(select(WatchItem.symbol)).all() == ["AAA"]
    assert db.scalar(select(func.count()).select_from(WatchItem)) == 1
