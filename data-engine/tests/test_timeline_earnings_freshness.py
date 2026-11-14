from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm.attributes import set_committed_value

from app.models import EarningsDate
from app.services import company_events_service as service
from app.services.earnings_dates_service import STALE_AFTER
from tests.test_company_timeline_events import _company, _memory_db

NOW = datetime(2026, 11, 14, 7, tzinfo=UTC)


@pytest.mark.parametrize('age,source,day,notice', [
    (timedelta(days=30), 'yahoo', date(2026, 11, 20), 'Dato desactualizado: última consulta 2026-10-15; la fecha puede haber cambiado'),
    (timedelta(days=30), 'yahoo', NOW.date(), 'Dato desactualizado: última consulta 2026-10-15; la fecha puede haber cambiado'),
    (STALE_AFTER, 'yahoo', date(2026, 11, 20), None),
    (timedelta(hours=1), 'yahoo', date(2026, 11, 20), None),
    (timedelta(days=30), 'manual', date(2026, 11, 20), None),
    (timedelta(days=30), 'yahoo', date(2026, 11, 10), None),
    (None, 'yahoo', date(2026, 11, 20), 'Fecha de consulta no disponible; no se puede verificar la vigencia'),
])
def test_timeline_discloses_only_automatic_upcoming_staleness(monkeypatch, age, source, day, notice):
    monkeypatch.setattr(service, '_utcnow', lambda: NOW)
    with _memory_db() as db:
        db.info['tenant_id'] = 1
        company = _company(db, 'FRESHNESS')
        row = EarningsDate(ticker=company.ticker, event_date=day, source=source, source_label='Source',
                           confirmed=True, fetched_at=NOW-age if age is not None else NOW,
                           source_url='https://example.com/source')
        db.add(row)
        db.commit()
        if age is None:
            # Legacy/malformed in-memory row: SQL schema is currently non-nullable.
            set_committed_value(row, 'fetched_at', None)
        result = service.stored_timeline_events(db, company, date(2026, 11, 1), date(2026, 11, 30))[0]
        assert result['detail'] == 'Fecha confirmada por la fuente' + ('\n'+notice if notice else '')
        assert result['date'] == day.isoformat()
        assert result['source'] == 'Source'
        assert result['source_url'] == 'https://example.com/source'
