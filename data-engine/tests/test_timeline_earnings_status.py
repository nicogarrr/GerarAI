from datetime import date

import pytest

from app.models.entities import EarningsDate
from app.services.company_events_service import stored_timeline_events
from tests.test_company_timeline_events import _company, _memory_db


@pytest.mark.parametrize('confirmed,notice', [
    (True, 'Fecha confirmada por la fuente'),
    (False, 'Fecha estimada por la fuente; puede cambiar'),
    (None, 'La fuente no indica si la fecha está confirmada'),
])
def test_timeline_keeps_earnings_date_status(confirmed, notice):
    with _memory_db() as db:
        company = _company(db, 'STATUS')
        db.add(EarningsDate(ticker='STATUS', event_date=date(2026, 11, 20), confirmed=confirmed,
                            source='yahoo', source_label='Yahoo Finance', source_url='https://example.com/source'))
        db.commit()
        row = stored_timeline_events(db, company, date(2026, 11, 1), date(2026, 11, 30))[0]
        assert row['detail'] == notice
        assert row['date'] == '2026-11-20'
        assert row['source'] == 'Yahoo Finance'
        assert row['source_url'] == 'https://example.com/source'
