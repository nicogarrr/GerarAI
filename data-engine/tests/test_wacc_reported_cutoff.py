from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, FinancialFact
from app.services.metric_calculation_service import MetricCalculationService
from tests.test_wacc_gasto_financiero_desfasado import _company, _fact, _inputs


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.mark.parametrize('year,accepted', [(2025, True), (2023, True), (2022, False), (2017, False), (2020, False)])
def test_reported_cost_same_two_year_gate(db, year, accepted):
    company = _company(db)
    _inputs(db, company, interest_year=2025)
    db.add(_fact(company, 'cost_of_debt', '.051', year=year, unit='decimal'))
    db.commit()
    result = MetricCalculationService().calculate(db, company, 'wacc', persist=False)
    assert (result.status == 'ok') == accepted
    if not accepted:
        assert result.value is None
        assert 'reported_cost_of_debt_same_period_as_debt' in result.calculation_trace['missing_inputs']


def test_cutoff_before_limit_filing_restatement_and_current_cache(db):
    company = _company(db)
    historical = _fact(company, 'beta', '.7', year=2025)
    historical.filed = date(2026, 9, 20)
    historical.created_at = datetime(2026, 11, 4, tzinfo=UTC)
    rows = [historical]
    for i in range(25):
        f = _fact(company, 'beta', '9', year=2025)
        f.filed = date(2026, 9, 25)
        rows.append(f)
    db.add_all(rows)
    db.commit()
    db.info['metric_calculation_facts_cache'] = {(company.id, 'beta'): rows[1:]}
    db.info['metric_calculation_as_of'] = date(2026, 9, 23)
    selected = MetricCalculationService()._facts_for_metric(db, company, 'beta')
    assert [f.id for f in selected] == [historical.id]


def test_no_filed_uses_created_and_rejects_future_period(db):
    company = _company(db)
    for period, created, value in [('2026-09-22', 22, '.7'), ('2026-09-25', 22, '9'), ('2026-09-22', 25, '8')]:
        f = _fact(company, 'beta', value, year=2026)
        f.period = period
        f.created_at = datetime(2026, 9, created, tzinfo=UTC)
        db.add(f)
    db.commit()
    db.info['metric_calculation_as_of'] = date(2026, 9, 23)
    rows = MetricCalculationService()._facts_for_metric(db, company, 'beta')
    assert [r.value for r in rows] == [Decimal('.7')]


def test_calculate_as_of_restores_context_and_ignores_future_inputs(db):
    company = _company(db)
    _inputs(db, company, interest_year=2025)
    for fact in db.query(FinancialFact).all():
        fact.filed = date(2026, 9, 20)
    future = _fact(company, 'cost_of_debt', '.051', year=2025, unit='decimal')
    future.filed = date(2026, 9, 25)
    db.add(future)
    db.commit()
    result = MetricCalculationService().calculate(db, company, 'wacc', persist=False, as_of=date(2026, 9, 23))
    assert result.status == 'ok'
    assert result.calculation_trace['cost_of_debt_source'] == 'interest_expense_over_debt'
    assert 'metric_calculation_as_of' not in db.info
