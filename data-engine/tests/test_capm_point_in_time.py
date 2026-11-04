"""El CAPM sectorial respeta la disponibilidad histórica de cada entrada."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact
from app.models.entities import Base
from app.valuation.engines.sector_specific import capm_cost_of_equity


def test_capm_uses_only_inputs_available_at_cutoff():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(ticker="PITCAPM", name="PIT", currency="USD", exchange="TEST", company_type="insurer", valuation_model="unassigned")
        db.add(company)
        db.flush()
        def add(metric, value, year, filed):
            db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(str(value)),
                                 unit="decimal", period=str(year), fiscal_year=year, fiscal_quarter="FY",
                                 source_type="test", is_reported=True, confidence=Decimal("0.9"), filed=filed))
        for metric, value in (("risk_free_rate", .03), ("beta", 1), ("equity_risk_premium", .05)):
            add(metric, value, 2023, date(2024, 2, 1))
        add("risk_free_rate", .09, 2025, date(2026, 2, 1))
        add("country_risk_premium", .04, 2025, None)
        db.flush()
        context = SimpleNamespace(db=db, company=company, as_of=date(2024, 6, 1))
        result = capm_cost_of_equity(context)
        assert result is not None
        assert abs(result.value - .08) < 1e-12
        context.as_of = date(2023, 1, 1)
        assert capm_cost_of_equity(context) is None
        context.as_of = None
        assert abs(capm_cost_of_equity(context).value - .18) < 1e-12
    engine.dispose()
