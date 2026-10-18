from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import FinancialFact
from app.services.long_term_model_service import LongTermModelService


def fact(id, year, period, quarter, value):
    return FinancialFact(id=id, company_id=1, metric='revenue', value=Decimal(value),
                         fiscal_year=year, period=period, fiscal_quarter=quarter,
                         unit='USD', source_type='SEC', confidence=Decimal('0.95'))


def test_driver_prefers_current_annual_over_old_undated_quarter_and_new_quarter():
    service = LongTermModelService()
    current = fact(2, 2025, '2026-01-30:FY', 'FY', '86290000000')
    stale = fact(3, None, '2022-10-28:Q3', 'Q3', '23480000000')
    next_quarter = fact(4, 2026, '2026-05-01:Q1', 'Q1', '21000000000')
    framework = SimpleNamespace(revenue_drivers=['revenue'], kpis=[], required_fact_metrics=['revenue'])
    company = SimpleNamespace(currency='USD')
    driver = service._driver_model(company, framework, {'revenue': [stale, current, next_quarter]})[0]
    assert driver['value'] == 86290000000
    assert driver['source_fact_ids'] == [2]


def test_fact_cap_keeps_latest_annual_history_not_oldest_200():
    engine = create_engine('sqlite://')
    FinancialFact.__table__.create(engine)
    with Session(engine) as db:
        for i in range(1, 206):
            db.add(fact(i, 2000 + i // 10, f'{2000 + i // 10}-12-31:FY', 'FY', str(i)))
        db.add(fact(206, None, '1999-09-30:Q3', 'Q3', '1'))
        db.flush()
        facts = LongTermModelService()._facts(db, SimpleNamespace(id=1), 'revenue')
        assert len(facts) == 200
        assert facts[-1].id == 205
        assert 1 not in {f.id for f in facts}
        assert 206 not in {f.id for f in facts}
