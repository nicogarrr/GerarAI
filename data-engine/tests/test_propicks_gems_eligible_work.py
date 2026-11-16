"""Ineligible companies must not enter the financial-fact window at all."""
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import event

from app.models import MarketPrice
from app.services import propicks_gems_service as gems
from app.services.propicks_funnel_service import FunnelResult
from tests.test_propicks_funnel import _company, _db, _fact


def result(company):
    return FunnelResult(company_id=company.id,
                        passed=True, score=50, metrics={'roic': .2, 'wacc': .08})


def test_no_usd_or_fresh_price_skips_facts_insiders_and_13f():
    today = date(2026, 11, 16)
    with _db() as db:
        eur, stale = _company('EUR', currency='EUR'), _company('STALE')
        db.add_all([eur, stale]); db.flush()
        db.add(MarketPrice(company_id=stale.id, date=today-timedelta(days=8), close=Decimal('10')))
        db.commit()
        statements = []
        def record(conn, cursor, statement, parameters, context, many):
            statements.append(statement)
        event.listen(db.get_bind(), 'before_cursor_execute', record)
        try:
            assert gems.find_gems(db, [result(eur)], today=today) == []
            assert gems.find_gems(db, [result(stale)], today=today) == []
        finally:
            event.remove(db.get_bind(), 'before_cursor_execute', record)
        assert not any(table in sql for sql in statements
                       for table in ['financial_facts', 'insider_transactions', 'manager_holdings'])


def test_fcf_sql_scopes_to_priced_eligible_companies_with_exact_parity(monkeypatch):
    today = date(2026, 11, 16)
    with _db() as db:
        eligible, stale, unpassed = [_company(t) for t in ['ELIGIBLE', 'STALE', 'UNPASSED']]
        db.add_all([eligible, stale, unpassed]); db.flush()
        for company in [eligible, stale, unpassed]:
            _fact(db, company, 'free_cash_flow', '150000000', 2025)
            _fact(db, company, 'shares_diluted', '100000000', 2025)
        db.add(MarketPrice(company_id=eligible.id, date=today, close=Decimal('10')))
        db.commit()
        expected = gems._latest_fcf_and_shares(db, 2024)[eligible.id]
        captured = []
        def record(conn, cursor, statement, parameters, context, many):
            if 'financial_facts' in statement:
                captured.append((statement, parameters))
        event.listen(db.get_bind(), 'before_cursor_execute', record)
        try:
            picked = gems.find_gems(db, [result(eligible), result(stale)], today=today)
        finally:
            event.remove(db.get_bind(), 'before_cursor_execute', record)
        original = gems._latest_fcf_and_shares
        with monkeypatch.context() as patch:
            patch.setattr(gems, '_latest_fcf_and_shares',
                          lambda db, cutoff, **kwargs: original(db, cutoff))
            reference = gems.find_gems(db, [result(eligible), result(stale)], today=today)
        assert [asdict(g) for g in picked] == [asdict(g) for g in reference]
        assert [g.ticker for g in picked] == ['ELIGIBLE']
        assert picked[0].market_cap == 10*expected[1]
        assert len(captured) == 1
        assert 'financial_facts.company_id IN' in captured[0][0]
        scoped = gems._latest_fcf_and_shares(db, 2024, company_ids=[eligible.id])
        assert scoped == {eligible.id: expected}
        assert gems._latest_fcf_and_shares(db, 2024, company_ids=[]) == {}
