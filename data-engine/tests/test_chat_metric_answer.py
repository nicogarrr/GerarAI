from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact
from app.models.entities import Base
from app.services.chat_metric_answer import metric_question_answer


def test_margin_same_period_not_gross_and_stores_no_dump():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        company = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", company_type="operating", valuation_model="unassigned")
        db.add(company)
        db.flush()
        for metric, value, period in [("revenue", "100", "2025:FY"), ("free_cash_flow", "25", "2025:FY"), ("free_cash_flow", "80", "2024:FY")]:
            db.add(FinancialFact(tenant_id=1, company_id=company.id, metric=metric, value=Decimal(value), unit="USD", period=period, fiscal_year=int(period[:4]), source_type="SEC", is_reported=True))
        db.flush()
        response = metric_question_answer(db, "¿Cuál es el margen FCF de Apple?", company)
        assert "25,00 %" in response.answer
        assert len(response.sources) == 2
        assert all(source["url"] for source in response.sources)
        stores = metric_question_answer(db, "¿Cuántas tiendas físicas tiene Apple?", company)
        assert "No tengo un recuento verificado" in stores.answer
        assert "25,00" not in stores.answer
        assert metric_question_answer(db, "Hola", company) is None


def test_margin_rejects_manual_and_nonreported_facts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        company = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", company_type="operating", valuation_model="unassigned")
        db.add(company)
        db.flush()
        for source, reported, period in [("manual", True, "2025:FY"), ("SEC", False, "2024:FY")]:
            for metric in ["revenue", "free_cash_flow"]:
                db.add(FinancialFact(tenant_id=1, company_id=company.id, metric=metric, value=Decimal("100"), unit="USD", period=period, fiscal_year=int(period[:4]), source_type=source, is_reported=reported))
        db.flush()
        response = metric_question_answer(db, "¿Cuál es el margen FCF de Apple?", company)
        assert "No puedo calcular" in response.answer
        assert "verificados del mismo periodo" in response.answer
        assert response.sources == []
        assert "100,00 %" not in response.answer
