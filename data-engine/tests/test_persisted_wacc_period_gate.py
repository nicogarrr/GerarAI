"""Old persisted WACC cannot bypass the calculator's existing period guard."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, CalculatedMetric, Company
from app.valuation.engines.base import traceable_wacc


@pytest.mark.parametrize('interest_period,expected', [
    ('2013-12-31:FY', None), ('2022-12-31:FY', None), ('unknown', None),
    ('2023-12-31:FY', .08), ('2025-12-31:FY', .08),
])
def test_persisted_interest_debt_period_policy(interest_period, expected):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(ticker='SYNTH', name='Synthetic', exchange='TEST', currency='USD',
                          company_type='standard', valuation_model='standard_dcf',
                          special_sources=[], special_risks=[], factor_tags=[])
        db.add(company)
        db.flush()
        metric = CalculatedMetric(company_id=company.id, metric='wacc', status='ok',
                                  value=Decimal('.08'), period='2026-09-23', unit='decimal',
                                  definition_version='test', formula='test', source_fact_ids=[],
                                  calculation_trace={'cost_of_debt_source': 'interest_expense_over_debt',
                                      'inputs': {'interest_expense': {'period': interest_period},
                                                 'total_debt': {'period': '2025-12-31:FY'}}},
                                  created_at=datetime.now(UTC))
        db.add(metric)
        db.commit()
        assert traceable_wacc(db, company) == expected
        assert metric.value == Decimal('.08')  # no rewrite or replacement
        assert not db.dirty
