"""Financial projections must bound rows before Python receives vintages."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import FinancialFact
from app.services import propicks_funnel_service as funnel
from app.services import propicks_gems_service as gems
from tests.test_propicks_funnel import _company, _db


class _Result:
    def __init__(self, result, budget):
        self.result = result
        self.budget = budget
    def all(self):
        rows = self.result.all()
        assert len(rows) <= self.budget, f'{len(rows)} rows read, budget {self.budget}'
        return rows


class _BudgetDb:
    def __init__(self, db, budget):
        self.db, self.info, self.budget = db, db.info, budget
    def execute(self, statement):
        return _Result(self.db.execute(statement), self.budget)


def test_financial_work_is_bounded_before_returning_from_sql():
    with _db() as db:
        company = _company('WORK')
        db.add(company)
        db.flush()
        for metric in ['net_income', 'revenue', 'free_cash_flow', 'shares_diluted']:
            for year in range(2000, 2027):
                for revision in range(30):
                    db.add(FinancialFact(company_id=company.id, metric=metric,
                        fiscal_year=year, fiscal_quarter='FY', period=f'FY{year}',
                        value=Decimal(100+revision), source_type='test',
                        created_at=datetime(2026, 1, 1, tzinfo=UTC)+timedelta(seconds=revision)))
        db.commit()
        assert funnel._earnings_consistency(_BudgetDb(db, 5)) == {company.id: (5, 5)}
        assert funnel._revenue_cagr(_BudgetDb(db, 2)) == {company.id: 0.0}
        assert gems._latest_fcf_and_shares(_BudgetDb(db, 2), 2024) == {company.id: (129.0, 129.0, 'FY2026')}
