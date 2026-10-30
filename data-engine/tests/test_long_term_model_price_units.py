"""El precio del modelo a largo plazo va en la divisa PRINCIPAL del listado.

Londres guarda el cierre en peniques (1.500 GBp = 15 £). El modelo guardaba
el cierre crudo como ``current_price`` y la tarjeta de valoración lo mostraba
como «precio del modelo 1.500 £».
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, FinancialFact, MarketPrice
from app.services.long_term_model_service import LongTermModelService

TICKER = "LTPEN.L"


def _cleanup(db) -> None:
    company = db.scalar(select(Company).where(Company.ticker == TICKER))
    if company:
        db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
        db.execute(delete(MarketPrice).where(MarketPrice.company_id == company.id))
        db.delete(company)
        db.commit()


@pytest.fixture
def db():
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    _cleanup(session)
    session.close()


def test_london_close_in_pence_is_published_in_pounds(db):
    company = Company(
        ticker=TICKER, name="Pence plc", exchange="LSE", currency="GBP",
        sector="Industrials", industry="Test", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    for year, revenue in ((2023, 900.0), (2024, 1000.0)):
        for metric, value, unit in (
            ("revenue", revenue, "GBP"),
            ("free_cash_flow", revenue * 0.2, "GBP"),
            ("net_debt", 100.0, "GBP"),
            ("shares_diluted", 100.0, "shares"),
        ):
            db.add(FinancialFact(
                company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
                period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY",
                source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
            ))
    db.add(MarketPrice(
        company_id=company.id, date=date(2026, 10, 20), open=Decimal("1500"),
        high=Decimal("1500"), low=Decimal("1500"), close=Decimal("1500"),
        adj_close=Decimal("1500"), volume=1, source="yfinance", quote_currency="GBp",
    ))
    db.commit()
    model = LongTermModelService().build(db, company)
    # 1.500 peniques / 100 = 15 £
    assert model["current_price"] == pytest.approx(15.0)
    assert model["reverse_dcf"]["market_price"] == pytest.approx(15.0)
