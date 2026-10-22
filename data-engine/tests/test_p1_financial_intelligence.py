from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    CalculatedMetric,
    Company,
    Document,
    FinancialFact,
    MarketPrice,
    Tenant,
)
from app.services.financial_terminal_service import FinancialTerminalService
from app.services.management_credibility_service import ManagementCredibilityService
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService
from app.services.portfolio_ledger_service import PortfolioLedgerService
from app.services.portfolio_snapshot_service import PortfolioSnapshotService


def _company() -> Company:
    return Company(
        ticker="PONE",
        name="P1 Company",
        exchange="NASDAQ",
        currency="USD",
        sector="Technology",
        industry="Software",
        company_type="software_ai",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=["quality", "growth"],
    )


def test_financial_terminal_portfolio_intelligence_and_management_scorecard():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="p1-intelligence", name="P1 intelligence")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        company = _company()
        db.add(company)
        db.flush()
        filing = Document(
            company_id=company.id,
            title="FY2025 filing",
            source_type="sec_filing",
            source_url="https://sec.gov/example",
            metadata_={"segment": "Cloud"},
        )
        db.add(filing)
        db.flush()
        for year, revenue, eps, shares in (
            (2023, "80", "2", "10"),
            (2024, "95", "2.5", "9.8"),
            (2025, "110", "3", "9.5"),
        ):
            for metric, value, unit in (
                ("revenue", revenue, "USD"),
                ("eps", eps, "USD/share"),
                ("shares_diluted", shares, "shares"),
            ):
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric=metric,
                        value=Decimal(value),
                        unit=unit,
                        period=f"FY{year}",
                        fiscal_year=year,
                        fiscal_quarter="FY",
                        source_id=filing.id,
                        source_type="sec_filing",
                        confidence=Decimal("0.95"),
                    )
                )
        db.add(
            FinancialFact(
                company_id=company.id,
                metric="revenue",
                value=Decimal("30"),
                unit="USD",
                period="Q1FY2025",
                fiscal_year=2025,
                fiscal_quarter="Q1",
                source_id=filing.id,
                source_type="sec_filing",
                confidence=Decimal("0.95"),
            )
        )
        db.add(
            CalculatedMetric(
                company_id=company.id,
                metric="roic",
                value=Decimal("0.18"),
                unit="decimal",
                period="FY2025",
                fiscal_year=2025,
                status="ok",
                definition_version="ROIC_STANDARD_V2",
                formula="nopat / invested_capital",
                source_fact_ids=[],
                calculation_trace={"method": "test"},
                confidence=Decimal("0.9"),
            )
        )
        db.commit()

        terminal = FinancialTerminalService().build(
            db,
            company,
            metrics=["revenue", "roic", "owner_earnings"],
            years=10,
        )
        revenue = next(item for item in terminal["metrics"] if item["metric"] == "revenue")
        roic = next(item for item in terminal["metrics"] if item["metric"] == "roic")
        assert {row["frequency"] for row in revenue["series"]} == {"annual", "quarterly"}
        assert {row["segment"] for row in revenue["series"]} == {"Cloud"}
        assert revenue["series"][0]["source"]["document_id"] == filing.id
        assert roic["series"][0]["formula"] == "nopat / invested_capital"
        assert terminal["coverage"]["missing"] == ["owner_earnings"]

        fx = PortfolioFXService()
        fx.set_base_currency(db, "EUR")
        start = date.today() - timedelta(days=30)
        fx.upsert_rate(
            db,
            base_currency="EUR",
            quote_currency="USD",
            rate=Decimal("0.8"),
            rate_date=start,
            source="test",
        )
        ledger = PortfolioLedgerService()
        ledger.create_transaction(
            db,
            ticker=company.ticker,
            action="buy",
            quantity=Decimal("10"),
            price=Decimal("100"),
            trade_date=start,
            currency="USD",
        )
        for offset in range(31):
            price = Decimal("100") + Decimal(offset) / Decimal("3")
            db.add(
                MarketPrice(
                    company_id=company.id,
                    date=start + timedelta(days=offset),
                    close=price,
                    adj_close=price,
                    source="test",
                )
            )
        ledger.update_market_price(
            db,
            company_id=company.id,
            price=Decimal("110"),
            as_of=date.today(),
        )
        db.commit()
        portfolio = PortfolioIntelligenceService().build(db, years=1)
        assert portfolio["performance"]["twr"] is not None
        assert portfolio["performance"]["xirr"] is not None
        assert portfolio["risk"]["volatility"] is not None
        assert portfolio["risk"]["max_drawdown"] == 0
        assert portfolio["concentration"]["top_1"] == 1
        assert portfolio["exposures"]["sectors"] == {"Technology": 1.0}
        assert portfolio["exposures"]["currencies"] == {"USD": 1.0}
        # La ventana de precios es de 30 dias (ano fiscal 2026 como mucho):
        # los facts anuales 2024-2025 quedan fuera, asi que no se atribuye una
        # recompra de varios anos a un retorno de un mes.
        assert portfolio["attribution"]["positions"][0]["components"]["buybacks"] is None

        snapshot_service = PortfolioSnapshotService()
        ledger.update_market_price(
            db,
            company_id=company.id,
            price=Decimal("105"),
            as_of=date.today() - timedelta(days=1),
        )
        first_snapshot = snapshot_service.capture(
            db,
            as_of=date.today() - timedelta(days=1),
            source="test",
        )
        ledger.update_market_price(
            db,
            company_id=company.id,
            price=Decimal("110"),
            as_of=date.today(),
        )
        second_snapshot = snapshot_service.capture(db, as_of=date.today(), source="test")
        db.commit()
        assert first_snapshot.pricing_coverage == 1
        assert second_snapshot.daily_return is not None
        snapshot_portfolio = PortfolioIntelligenceService().build(db, years=1)
        assert snapshot_portfolio["performance"]["twr_is_exact"] is True
        assert snapshot_portfolio["performance"]["twr_method"] == (
            "daily_portfolio_snapshots"
        )

        promise = ManagementCredibilityService().register(
            db,
            company,
            promise="Revenue will be at least 100 in FY2025",
            promise_date=date(2024, 2, 1),
            expected_period="FY2025",
            metric="revenue",
            operator=">=",
            target_value=Decimal("100"),
            unit="USD",
            source_document_id=filing.id,
        )
        ManagementCredibilityService().set_explanation(
            db, promise, "Cloud demand exceeded the original plan."
        )
        promise.metadata_ = {
            **(promise.metadata_ or {}),
            "reviewed_at": "2026-10-22T12:00:00+00:00",
            "review_kind": "user_declared",
        }
        db.commit()
        ManagementCredibilityService().reconcile(db, company)
        dashboard = ManagementCredibilityService().dashboard(db, company)
        assert dashboard["score"] == 1
        assert dashboard["grade"] == "high"
        assert dashboard["promises"][0]["status"] == "met"
        assert dashboard["promises"][0]["actual_fact_id"] is not None
