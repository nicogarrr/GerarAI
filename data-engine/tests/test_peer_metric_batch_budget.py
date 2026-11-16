"""Comparing peers must share bounded input reads across participants."""
from sqlalchemy import event

from app.services.peer_comparison_service import PeerComparisonService
from tests.test_peer_selection_query_count import _session


def test_peer_comparison_has_one_fact_prefetch_for_all_participants():
    engine, db, companies = _session(9)
    queries = []
    def before(_conn, _cursor, sql, *_args):
        if 'row_number()' in sql.lower() and 'financial_facts' in sql and 'financial_facts.metric' in sql:
            queries.append(sql)
    event.listen(engine, 'before_cursor_execute', before)
    try:
        result = PeerComparisonService().compare(db, companies[0])
        assert len(result['companies']) == 9
        # Selection's market-cap ranking is separate and is not a metric prefetch.
        metric_prefetches = [sql for sql in queries if 'rn' in sql and 'metric IN' in sql]
        assert len(metric_prefetches) == 1, len(metric_prefetches)
    finally:
        db.close()
        engine.dispose()


def test_prefetch_batch_preserves_cap_per_company_metric_and_cleans_on_error():
    from decimal import Decimal

    import pytest

    from app.models import FinancialFact
    from app.services.metric_calculation_service import (
        _FACTS_CACHE_KEY,
        _FACTS_PER_METRIC,
        MetricCalculationService,
    )
    engine, db, companies = _session(3)
    try:
        for company in companies:
            for i in range(_FACTS_PER_METRIC + 30):
                db.add(FinancialFact(company_id=company.id, metric='revenue', value=Decimal(i),
                    unit='USD', period=f'FY{1900+i}', fiscal_year=1900+i, source_type='test'))
        db.commit()
        db.expunge_all()
        loaded = []
        def onload(_db, row):
            if isinstance(row, FinancialFact):
                loaded.append(row)
        event.listen(db, 'loaded_as_persistent', onload)
        service = MetricCalculationService()
        # Company identities are retained by the fixture, not their fact rows.
        with service.prefetched_companies(db, companies):
            actual = {c.id: service._facts_for_metric(db, c, 'revenue') for c in companies}
            assert all(len(rows) == _FACTS_PER_METRIC for rows in actual.values())
            assert len(loaded) <= len(companies) * (_FACTS_PER_METRIC + 2)
        event.remove(db, 'loaded_as_persistent', onload)
        assert _FACTS_CACHE_KEY not in db.info
        for company in companies:
            assert [row.id for row in actual[company.id]] == [row.id for row in service._facts_for_metric(db, company, 'revenue')]
        with pytest.raises(RuntimeError, match='abort'):
            with service.prefetched_companies(db, companies):
                raise RuntimeError('abort')
        assert _FACTS_CACHE_KEY not in db.info
    finally:
        db.close()
        engine.dispose()


def test_batch_empty_nested_and_tenant_cache_are_request_scoped():
    from decimal import Decimal

    from app.models import FinancialFact
    from app.services.metric_calculation_service import _FACTS_CACHE_KEY, MetricCalculationService
    engine, db, companies = _session(2)
    try:
        service = MetricCalculationService()
        service._prefetch_company_ids(db, [], {})
        with service.prefetched_companies(db, []):
            cache = db.info[_FACTS_CACHE_KEY]
            with service.prefetched_companies(db, companies):
                assert db.info[_FACTS_CACHE_KEY] is cache
            assert _FACTS_CACHE_KEY in db.info
        assert _FACTS_CACHE_KEY not in db.info
        db.info['tenant_id'] = 2
        db.add(FinancialFact(company_id=companies[0].id, metric='revenue', value=Decimal('999'),
                            unit='USD', fiscal_year=2026, period='FY2026', source_type='test'))
        db.commit()
        with service.prefetched_companies(db, companies):
            assert service._facts_for_metric(db, companies[0], 'revenue')[0].value == 999
        db.info['tenant_id'] = 1
        with service.prefetched_companies(db, companies):
            assert service._facts_for_metric(db, companies[0], 'revenue') == []
    finally:
        db.close()
        engine.dispose()


def test_prefetch_chunks_every_company_and_releases_cache(monkeypatch):
    from types import SimpleNamespace

    from app.services.metric_calculation_service import _FACTS_CACHE_KEY, MetricCalculationService

    service = MetricCalculationService()
    db = SimpleNamespace(info={})
    batches = []
    monkeypatch.setattr(service, '_prefetch_company_ids', lambda db, ids, cache: batches.append(ids))
    companies = [SimpleNamespace(id=i) for i in range(205)]
    with service.prefetched_companies(db, companies):
        assert _FACTS_CACHE_KEY in db.info
    assert batches == [list(range(100)), list(range(100, 200)), list(range(200, 205))]
    assert _FACTS_CACHE_KEY not in db.info


def test_peer_reference_missing_table_is_an_inert_axis():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.services.peer_comparison_service import _reference_taxonomy

    engine = create_engine('sqlite:///:memory:')
    try:
        with Session(engine) as db:
            assert _reference_taxonomy(db, []) == {}
            assert _reference_taxonomy(db, ['AAPL']) == {}
    finally:
        engine.dispose()


def test_capital_units_and_unknown_years_do_not_imply_comparability():
    from decimal import Decimal

    from app.models import FinancialFact
    from app.services.metric_calculation_service import _capital_scale_conflict, _fact_year, _fiscal_year_gap

    equity = FinancialFact(value=Decimal('100'), unit='USD', period='2026-Q3', source_type='test')
    debt = FinancialFact(value=Decimal('20'), unit='EUR', period='unknown', source_type='test')
    assert _capital_scale_conflict(equity, debt) is True
    assert _fact_year(equity) == 2026
    assert _fact_year(debt) is None
    assert _fiscal_year_gap(equity, debt) is None
    debt.value = Decimal('0')
    assert _capital_scale_conflict(equity, debt) is False
