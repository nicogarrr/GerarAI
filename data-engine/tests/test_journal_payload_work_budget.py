"""Request-local history reuse without broadening any historical query."""
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import event, select

from app.models import DecisionJournalEntry, ValuationModel
from app.services.fundamental_review_service import DecisionJournalService
from app.services.journal_trade_link import journal_entry_payload
from tests.test_journal_trade_link import _company, _engine, _thesis, _trade, db  # noqa: F401


def _fixture(db, count):
    company = _company(db)
    _thesis(db, company, version=1, created=datetime(2024, 1, 1, tzinfo=UTC), expected='100')
    # Invalid models before the valid one exercise output lookup short circuits.
    for version in range(1, 5):
        _engine(db, company, version=version, created=datetime(2024, 1, 1, tzinfo=UTC), expected=120)
    models = list(db.scalars(select(ValuationModel).where(ValuationModel.company_id == company.id)))
    for row in models[1:]:
        row.status = 'archived'
    for i in range(count):
        trade = _trade(db, company, day=date(2026, 3, i + 1), price=str(60 + i))
        db.add(DecisionJournalEntry(company_id=company.id, decision='buy', rationale='test',
                                   what_must_be_true=[], transaction_id=trade.id,
                                   decision_date=trade.trade_date, price=Decimal('70')))
    db.commit()
    # Do not let fixture object retention mask repeated ORM loading.
    company_id = company.id
    db.expunge_all()
    return company_id


def _measure(db, count):
    company_id = _fixture(db, count)
    from app.models import Company
    company = db.get(Company, company_id)
    entries = DecisionJournalService().list(db, company)
    queries = []
    loads = []
    def before(_conn, _cursor, statement, *_args):
        queries.append(statement)
    def loaded(_session, row):
        loads.append(type(row).__name__)
    event.listen(db.bind, 'before_cursor_execute', before)
    event.listen(db, 'loaded_as_persistent', loaded)
    try:
        from app.services import journal_trade_link as service
        if hasattr(service, 'journal_entries_payload'):
            result = service.journal_entries_payload(db, company, entries)
        else:
            result = [journal_entry_payload(db, entry) for entry in entries]
    finally:
        event.remove(db.bind, 'before_cursor_execute', before)
        event.remove(db, 'loaded_as_persistent', loaded)
    expected = [journal_entry_payload(db, entry) for entry in entries]
    assert result == expected
    assert all(row['fair_value_on_day']['value'] == 120 for row in result)
    assert len(queries) <= 4, (len(queries), loads)
    assert loads.count('ThesisVersion') <= 1
    assert loads.count('ValuationModel') <= 4


def test_one_linked_entry_budget(db):
    _measure(db, 1)


def test_twenty_distinct_trade_days_same_read_budget(db):
    _measure(db, 20)


def test_empty_unlinked_missing_and_company_guard(db):
    import pytest

    from app.services.journal_trade_link import journal_entries_payload
    company = _company(db)
    assert journal_entries_payload(db, company, []) == []
    entry = DecisionJournalEntry(company_id=company.id, decision='hold', rationale='test',
                                 what_must_be_true=[])
    db.add(entry)
    db.flush()
    assert journal_entries_payload(db, company, [entry]) == [journal_entry_payload(db, entry)]
    entry.transaction_id = 99999
    assert journal_entries_payload(db, company, [entry]) == [journal_entry_payload(db, entry)]
    other = _company(db, 'OTHER')
    with pytest.raises(ValueError, match='misma empresa'):
        journal_entries_payload(db, other, [entry])


def test_point_in_time_and_request_cache_is_not_reused(db):
    from app.models import Company
    from app.services.journal_trade_link import journal_entries_payload
    company_id = _fixture(db, 3)
    company = db.get(Company, company_id)
    entries = DecisionJournalService().list(db, company)
    # All rows reused, but eligibility must still be evaluated for EACH trade.
    _thesis(db, company, version=2, created=datetime(2026, 3, 2, tzinfo=UTC), expected='150')
    result = journal_entries_payload(db, company, entries)
    assert result == [journal_entry_payload(db, entry) for entry in entries]
    assert [row['fair_value_on_day']['value'] for row in result] == [150, 150, 120]
    _thesis(db, company, version=3, created=datetime(2026, 3, 3, tzinfo=UTC), expected='180')
    assert journal_entries_payload(db, company, entries)[0]['fair_value_on_day']['value'] == 180


def test_missing_outputs_and_unused_output_histories_are_not_broad_loaded(db):
    from collections import Counter

    from app.models import Company, ValuationOutput
    from app.services.journal_trade_link import journal_entries_payload
    company_id = _fixture(db, 3)
    company = db.get(Company, company_id)
    # None output is cached too. Versions visited before the valid engine are
    # queried at most once, preserving LIMIT 1 instead of load-then-trim.
    missing = ValuationModel(company_id=company_id, model_type='standard_dcf', version=20,
                             status='final', calculation_trace={},
                             created_at=datetime(2024, 1, 1, tzinfo=UTC),
                             updated_at=datetime(2024, 1, 1, tzinfo=UTC))
    db.add(missing)
    models = list(db.scalars(select(ValuationModel).where(ValuationModel.company_id == company_id)))
    valid = next(row for row in models if row.version == 1)
    for i in range(30):
        db.add(ValuationOutput(valuation_model_id=valid.id, scenario=f'unused-{i}',
                               value_per_share=Decimal('1'), output_payload={'expected_value': 999}))
    db.commit()
    db.expunge_all()
    company = db.get(Company, company_id)
    entries = DecisionJournalService().list(db, company)
    loaded = Counter()
    statements = []
    def onload(_session, row):
        loaded[type(row).__name__] += 1
    def onquery(_conn, _cursor, sql, *_args):
        statements.append(sql)
    event.listen(db, 'loaded_as_persistent', onload)
    event.listen(db.bind, 'before_cursor_execute', onquery)
    try:
        result = journal_entries_payload(db, company, entries)
    finally:
        event.remove(db, 'loaded_as_persistent', onload)
        event.remove(db.bind, 'before_cursor_execute', onquery)
    assert result == [journal_entry_payload(db, entry) for entry in entries]
    assert len(statements) == 5
    assert loaded['ValuationOutput'] == 1
    assert loaded['ValuationModel'] == 5


def test_route_uses_batch_payload_builder(db, monkeypatch):
    from app.api.routes import companies
    from app.models import Company
    from app.services import journal_trade_link
    company_id = _fixture(db, 2)
    company = db.get(Company, company_id)
    called = []
    original = journal_trade_link.journal_entries_payload
    def counted(session, resolved, entries):
        called.append(len(entries))
        return original(session, resolved, entries)
    monkeypatch.setattr(journal_trade_link, 'journal_entries_payload', counted)
    assert len(companies.decision_journal(company.ticker, db)) == 2
    assert called == [2]


def test_large_journal_splits_bind_parameters_without_truncation(db):
    from app.models import Transaction
    from app.services.journal_trade_link import journal_entries_payload
    company = _company(db)
    transactions = [Transaction(company_id=company.id, trade_date=date(2026, 3, 1),
                                 action='buy', quantity=Decimal('1'), price=Decimal('70'),
                                 fees=Decimal('0'), currency='USD') for _ in range(501)]
    db.add_all(transactions)
    db.flush()
    entries = [DecisionJournalEntry(company_id=company.id, transaction_id=trade.id,
                                     decision='buy', rationale='test', what_must_be_true=[])
               for trade in transactions]
    db.add_all(entries)
    db.flush()
    parameters = []
    def before(_conn, _cursor, sql, params, *_args):
        if 'FROM transactions' in sql:
            parameters.append(len(params))
    event.listen(db.bind, 'before_cursor_execute', before)
    try:
        result = journal_entries_payload(db, company, entries)
    finally:
        event.remove(db.bind, 'before_cursor_execute', before)
    assert len(result) == 501
    assert parameters == [500, 1]
    assert all(row['transaction'] is not None for row in result)
    assert all(row['fair_value_on_day'] is None for row in result)


def test_same_company_different_tenants_get_fresh_scoped_history(db):
    from app.models import Company, Tenant
    from app.services.journal_trade_link import journal_entries_payload
    tenants = [Tenant(external_id=f'journal-scope-{i}', name=str(i), status='active', metadata_={})
               for i in range(2)]
    db.add_all(tenants)
    db.commit()
    a, b = [row.id for row in tenants]
    db.info['tenant_id'] = a
    company_id = _fixture(db, 2)
    company = db.get(Company, company_id)
    db.info['tenant_id'] = b
    _thesis(db, company, version=9, created=datetime(2026, 3, 1, tzinfo=UTC), expected='999')
    trade = _trade(db, company, day=date(2026, 3, 4))
    db.add(DecisionJournalEntry(company_id=company_id, transaction_id=trade.id,
                                decision='buy', rationale='B only', what_must_be_true=[]))
    db.commit()
    entries = DecisionJournalService().list(db, company)
    result_b = journal_entries_payload(db, company, entries)
    assert len(result_b) == 1 and result_b[0]['fair_value_on_day']['value'] == 999
    db.info['tenant_id'] = a
    entries = DecisionJournalService().list(db, company)
    result_a = journal_entries_payload(db, company, entries)
    assert len(result_a) == 2
    assert all(row['fair_value_on_day']['value'] == 120 for row in result_a)
