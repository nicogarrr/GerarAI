"""Ventana corta de snapshots: sin anualizar y con limitacion declarada."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice, Portfolio, PortfolioDailySnapshot, Position
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService


def test_short_snapshot_window_is_not_annualized():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "t"
        db.add(Portfolio(name="Main", base_currency="USD", is_default=True))
        company = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
                          sector="T", industry="T", company_type="holding",
                          valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[])
        db.add(company); db.commit()
        today = date.today()
        for i, px in enumerate(["100", "101", "102"]):
            day = today - timedelta(days=2 - i)
            db.add(MarketPrice(company_id=company.id, date=day, open=Decimal(px), high=Decimal(px),
                               low=Decimal(px), close=Decimal(px), adj_close=Decimal(px), source="probe"))
        position = Position(company_id=company.id, quantity=Decimal("10"), average_cost=Decimal("100"),
                            market_price=Decimal("102"), market_value=Decimal("1020"),
                            unrealized_pnl=Decimal("20"), realized_pnl=Decimal("0"), currency="USD",
                            base_currency="USD", market_value_native=Decimal("1020"),
                            cost_basis_native=Decimal("1000"), market_value_base=Decimal("1020"),
                            cost_basis_base=Decimal("1000"), as_of=today, source="probe")
        db.add(position); db.commit()
        # Dos snapshots dias seguidos, cobertura completa -> snapshot_exact=True con 1 retorno diario
        for i, (day, total) in enumerate([(today - timedelta(days=1), "1010"), (today, "1020")]):
            snap = PortfolioDailySnapshot(
                portfolio_id=1, snapshot_date=day, base_currency="USD",
                positions_value_base=Decimal(total), cash_value_base=Decimal("0"),
                total_value_base=Decimal(total), net_external_flow_base=Decimal("0"),
                daily_return=(Decimal("0.00990099") if i == 1 else None),
                cumulative_twr=(Decimal("0.00990099") if i == 1 else None),
                pricing_coverage=Decimal("1"), source="probe", metadata_={"ambiguous_external_flows": []})
            db.add(snap)
        db.commit()
        result = PortfolioIntelligenceService().build(db, years=5)
        perf = result["performance"]
        print("\ntwr_method:", perf["twr_method"], "| twr:", perf["twr"],
              "| annualized:", perf["annualized_return"])
        # Una ventana de 1 dia no se anualiza (antes: 1097 %).
        assert perf["twr_method"] == "daily_portfolio_snapshots"
        assert perf["twr"] == pytest.approx(0.0099, abs=1e-4)
        assert perf["annualized_return"] is None
        limitations = result["coverage"]["limitations"]
        assert any("Annualized return not shown" in item for item in limitations)
