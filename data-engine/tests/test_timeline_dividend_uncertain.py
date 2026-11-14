from datetime import date
from decimal import Decimal

import pytest

from app.models import DividendRecord
from app.services.company_events_service import stored_timeline_events
from tests.test_company_timeline_events import _company, _memory_db


@pytest.mark.parametrize('source,amounts,expected', [
    ('yahoo_finance', ['0.25', '1'], ['Importe incierto: la fuente guarda varios importes para esta fecha']),
    ('yahoo_finance', ['0.25'], ['0.25 USD por acción']),
    ('fmp', ['0.25', '1'], ['1 USD por acción', '0.25 USD por acción']),
])
def test_dividend_timeline_marks_uncertain_groups(source, amounts, expected):
    with _memory_db() as db:
        db.info['tenant_id'] = 1
        company = _company(db, 'DIVSTATUS')
        for amount in amounts:
            db.add(DividendRecord(company_id=company.id, ex_date=date(2026, 11, 20),
                                 amount=Decimal(amount), currency='USD', source=source))
        db.commit()
        rows = stored_timeline_events(db, company, date(2026, 11, 1), date(2026, 11, 30))
        assert [row['detail'] for row in rows] == expected
        assert all(row['date'] == '2026-11-20' and row['source'] == source for row in rows)
        assert all(row['kind'] == 'ex_dividend' for row in rows)
