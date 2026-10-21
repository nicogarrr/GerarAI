"""Empresa que dejo de facturar (ingreso anual 0 en el ultimo ano, p. ej. HYMC):
el reverse DCF no puede lanzar ValueError y tumbar la generacion de la tesis."""

from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, FinancialFact, MarketPrice
from app.services.long_term_model_service import LongTermModelService

TICKER = "ZRVX"


def _cleanup() -> None:
    init_db()
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == TICKER))
        if company:
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
            db.execute(delete(MarketPrice).where(MarketPrice.company_id == company.id))
            db.delete(company)
            db.commit()
    finally:
        db.close()


def _fact(db, company, metric, value, year, unit="USD"):
    db.add(
        FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
            period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY",
            source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
        )
    )


def test_ingreso_anual_cero_no_lanza_value_error():
    _cleanup()
    db = SessionLocal()
    try:
        company = Company(
            ticker=TICKER, name="Zero Revenue Mining", exchange="TEST", currency="USD",
            sector="Materials", industry="Gold", company_type="standard",
            valuation_model="standard_dcf", special_sources=[], special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.flush()
        for year, rev in ((2022, 46_000_000), (2023, 14_000_000), (2024, 0)):
            _fact(db, company, "revenue", rev, year)
            _fact(db, company, "net_income", -60_000_000, year)
            _fact(db, company, "free_cash_flow", -50_000_000, year)
            _fact(db, company, "net_debt", 100_000_000, year)
            _fact(db, company, "shares_diluted", 20_000_000, year, unit="shares")
        db.add(MarketPrice(company_id=company.id, date=date(2026, 10, 20), open=Decimal('2'), high=Decimal('2'), low=Decimal('2'), close=Decimal('2'), adj_close=Decimal('2'), volume=1000, source='TEST'))
        db.commit()
        model = LongTermModelService().build(db, company)
        assert model["publishable"] is False
        assert model["reverse_dcf"]["status"] == "insufficient_data"
        assert "revenue" in model["reverse_dcf"]["missing_inputs"]
    finally:
        db.close()
        _cleanup()
