from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.portfolio import _fx_source
from app.models.entities import Base, FXRate, Tenant


def test_fx_source_does_not_take_newer_other_tenant_label():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Tenant(id=1,external_id='one'),Tenant(id=2,external_id='two')]);db.commit()
        db.add_all([
            FXRate(tenant_id=1,base_currency='EUR',quote_currency='USD',rate=Decimal('.9'),rate_date=date(2026,10,28),source='owner-ecb'),
            FXRate(tenant_id=2,base_currency='EUR',quote_currency='USD',rate=Decimal('.8'),rate_date=date(2026,10,29),source='other-private-source'),
        ]);db.commit();db.info['tenant_id']=1
        assert _fx_source(db,'EUR')=={'source':'owner-ecb','latest_rate_date':'2026-10-28','base_currency':'EUR'}


def test_journal_column_read_contains_explicit_tenant_predicate():
    from app.services.journal_trade_link import auto_link_journal_trades
    from tests.test_journal_auto_link import _company, _db, _entry, _trade
    db=_db();company=_company(db);_entry(db,company);_trade(db,company,date(2026,3,10))
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT') and 'decision_journal_entries.transaction_id' in statement and 'NOT IN' in statement:
            statements.append(statement)
    event.listen(db.get_bind(),'before_cursor_execute',capture)
    try:auto_link_journal_trades(db)
    finally:event.remove(db.get_bind(),'before_cursor_execute',capture)
    assert statements
    assert all('decision_journal_entries.tenant_id =' in query for query in statements)


def test_refresh_fact_unit_column_read_contains_explicit_tenant_predicate():
    import asyncio

    from app.services.market_refresh_service import MarketRefreshService
    from tests.test_market_refresh_service import _FakeFXProvider, _FakePriceProvider, _seed
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False) as db:
        db.info['tenant_id']='tenant-test';_seed(db,1);statements=[]
        def capture(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().upper().startswith('SELECT DISTINCT financial_facts.unit'.upper()):statements.append(statement)
        event.listen(engine,'before_cursor_execute',capture)
        try:asyncio.run(MarketRefreshService(price_provider=_FakePriceProvider(),fx_provider=_FakeFXProvider()).refresh(db,as_of=date(2026,9,22)))
        finally:event.remove(engine,'before_cursor_execute',capture)
        assert statements
        assert all('financial_facts.tenant_id =' in query for query in statements)
