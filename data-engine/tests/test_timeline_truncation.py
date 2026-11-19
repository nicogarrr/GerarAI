"""Timeline cap is visible, counts exact, boundary dates not coverage claims."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.api.routes import company_events as route
from app.models import EarningsDate
from app.services.company_events_service import TIMELINE_MAX_EVENTS, stored_timeline_events
from app.services.timeline_collection import TimelineCollector, TimelineEvents
from tests.test_company_timeline_events import _company, _memory_db


@pytest.mark.parametrize('count', [0, 1, 500, 501, 525])
def test_route_reports_exact_total_cap_and_returned_dates(monkeypatch, count):
    with _memory_db() as db:
        company = _company(db, 'CAP')
        first = date(2020, 1, 1)
        for i in range(count):
            db.add(EarningsDate(ticker='CAP', event_date=first + timedelta(days=i), source='manual', source_label='Manual', fiscal_label=f'T{i}'))
        db.commit()
        monkeypatch.setattr(route, 'resolve_company', lambda db, ticker: company)
        body = route.get_company_timeline_events('CAP', desde=first, hasta=date(2026, 1, 1), db=db)
        validated = route.CompanyTimelineEventsOut.model_validate(body).model_dump()
    assert validated['total'] == count
    assert validated['limit'] == TIMELINE_MAX_EVENTS
    assert len(validated['events']) == min(count, TIMELINE_MAX_EVENTS)
    assert validated['truncated'] is (count > TIMELINE_MAX_EVENTS)
    assert bool(validated['notice']) is (count > TIMELINE_MAX_EVENTS)
    assert validated['desde'] == '2020-01-01' and validated['hasta'] == '2026-01-01'
    assert validated['returned_desde'] == ((first + timedelta(days=max(0, count - 500))).isoformat() if count else None)
    assert validated['returned_hasta'] == ((first + timedelta(days=count - 1)).isoformat() if count else None)


def test_equal_day_cut_is_explicit_and_collector_never_exceeds_cap(monkeypatch):
    collector = TimelineCollector(500)
    expected = []
    for i in range(1100):
        item = dict(id=f'news-{i}', date='2026-01-01', kind='news', title='Noticia', source='test')
        expected.append(item)
        collector.append(item)
        assert len(collector._heap) <= 500
    result = collector.result()
    assert result == sorted(expected, key=lambda e: (e['date'], e['id']), reverse=True)[:500]
    assert result.total == 1100 and result.truncated
    monkeypatch.setattr(route, 'resolve_company', lambda *_: SimpleNamespace(ticker='CAP', currency='USD'))
    monkeypatch.setattr(route, 'stored_timeline_events', lambda *_: result)
    monkeypatch.setattr(route, 'stored_holding', lambda *_: None)
    body = route.get_company_timeline_events('CAP', desde=date(2020, 1, 1), hasta=date(2026, 1, 1), db=None)
    assert body['returned_desde'] == body['returned_hasta'] == '2026-01-01'
    assert 'incompleto' in body['notice']


def test_streamed_queries_do_not_materialize_unbounded_results():
    with _memory_db() as db:
        company = _company(db, 'STREAM')
        db.commit()
        options = []
        def capture(conn, cursor, statement, params, context, many):
            if any(name in statement for name in ('earnings_dates', 'news_events', 'insider_transactions')):
                options.append(context.execution_options.get('yield_per'))
        event.listen(db.get_bind(), 'before_cursor_execute', capture)
        try:
            result = stored_timeline_events(db, company, date(2020, 1, 1), date(2026, 1, 1))
        finally:
            event.remove(db.get_bind(), 'before_cursor_execute', capture)
    assert result == [] and result.total == 0
    assert len(options) == 3 and options == [128, 128, 128]


def test_list_compatible_empty_result():
    result = TimelineEvents([], 0)
    assert result == [] and not result.truncated and result.total == 0
