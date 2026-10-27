import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select

from app.api.routes import portfolio
from app.core.database import Base
from app.models import Position, Transaction
from app.services.ibkr_import_service import IBKRImportService
from tests.test_ibkr_import import _tenant_session


def settings(owner=1, account='U1'):
    return SimpleNamespace(ibkr_flex_tenant_id=owner, ibkr_flex_account_id=account)


@pytest.mark.parametrize('owner,tenant', [(None, 1), (1, None), (1, 2), (True, 1), (1, True)])
def test_other_or_missing_owner_rejected_before_fetch_or_parse(monkeypatch, owner, tenant):
    monkeypatch.setattr(portfolio, 'get_settings', lambda: settings(owner))
    monkeypatch.setattr(portfolio, 'IBKRFlexClient', lambda: pytest.fail('must not access global credentials'))
    db = SimpleNamespace(info={'tenant_id': tenant})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(portfolio.import_ibkr(db))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        portfolio.import_ibkr_xml(portfolio.IBKRXmlImportRequest(xml='<not-a-real-statement/>'), db)
    assert exc.value.status_code == 403


def test_missing_account_closed(monkeypatch):
    monkeypatch.setattr(portfolio, 'get_settings', lambda: settings(account=''))
    with pytest.raises(HTTPException) as exc:
        portfolio._require_ibkr_owner(SimpleNamespace(info={'tenant_id': 1}, scalar=lambda query: None))
    assert exc.value.status_code == 503


@pytest.mark.parametrize('mode', ['xml', 'download'])
@pytest.mark.parametrize('account,age', [('OTHER', 0), ('U1', 6), ('U1', -1)])
def test_owner_wrong_account_or_statement_date_rejected_without_writes(monkeypatch, mode, account, age):
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}); Base.metadata.create_all(engine)
    with _tenant_session(engine) as db:
        monkeypatch.setattr(portfolio, 'get_settings', lambda: settings(owner=db.info['tenant_id']))
        day = (date.today() - timedelta(days=age)).strftime('%Y%m%d')
        xml = f'<FlexQueryResponse><FlexStatements><FlexStatement accountId="{account}" toDate="{day}"><Trade symbol="AAPL" tradeID="X" buySell="BUY" quantity="1" tradePrice="10" tradeDate="{day}"/></FlexStatement></FlexStatements></FlexQueryResponse>'
        class Client:
            def configured(self): return True
            async def fetch_latest_xml(self): return xml
        monkeypatch.setattr(portfolio, 'IBKRFlexClient', Client)
        with pytest.raises(HTTPException) as exc:
            if mode == 'xml': portfolio.import_ibkr_xml(portfolio.IBKRXmlImportRequest(xml=xml), db)
            else: asyncio.run(portfolio.import_ibkr(db))
        assert exc.value.status_code == 400
        assert db.query(Transaction).count() == 0 and db.query(Position).count() == 0


def test_owner_valid_statement_uses_merge_not_destructive_reconcile(monkeypatch):
    monkeypatch.setattr(portfolio, 'get_settings', lambda: settings())
    calls = []
    def fake(self, db, xml, **kw): calls.append(kw); return {'status': 'imported'}
    monkeypatch.setattr(IBKRImportService, 'import_flex_xml', fake)
    portfolio.import_ibkr_xml(portfolio.IBKRXmlImportRequest(xml='<fake-statement-long-enough/>'), SimpleNamespace(info={'tenant_id': 1}, scalar=lambda query: None))
    assert calls == [{'expected_account_id': 'U1', 'max_statement_age_days': 5}]


def test_csv_replay_reordering_formatting_and_identical_fills_idempotent():
    engine = create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    with _tenant_session(engine) as db:
        svc=IBKRImportService(); day=date.today().isoformat()
        head='symbol,action,quantity,price,date,fees,currency\n'
        a=f'AAPL,buy,1,10,{day},0,USD\n'; b=f'MSFT,buy,2,20,{day},0,USD\n'
        assert svc.import_ibkr_csv(db,head+a+a+b)['trades_imported']==3
        result=svc.import_ibkr_csv(db,head+b+a.replace(',1,10,',',1.0,10.00,')+a)
        assert result['trades_imported']==0 and result['duplicate_trades']==3
        assert db.query(Transaction).count()==3
        assert db.scalar(select(Position.quantity).where(Position.quantity==2))==2


def test_csv_provider_ids_dedup_in_file_and_cross_xml_identity():
    engine = create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    with _tenant_session(engine) as db:
        day=date.today().isoformat(); head='symbol,action,quantity,price,date,tradeID\n'
        csv=head+f'AAPL,buy,1,10,{day},T1\nAAPL,buy,1,10,{day},T1\n'
        r=IBKRImportService().import_ibkr_csv(db,csv)
        assert r['trades_imported']==1 and r['duplicate_trades']==1
        assert db.scalar(select(Transaction.external_id))=='T1'
        assert IBKRImportService().import_ibkr_csv(db,csv)['trades_imported']==0


def test_csv_idempotency_is_tenant_scoped():
    from app.models import Tenant
    engine = create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    with _tenant_session(engine) as db:
        first=db.info['tenant_id']; other=Tenant(external_id='other-csv',name='Other'); db.add(other); db.commit(); second=other.id
        csv='symbol,action,quantity,price,date,tradeID\n'+f'AAPL,buy,1,10,{date.today().isoformat()},SHARED\n'
        svc=IBKRImportService(); assert svc.import_ibkr_csv(db,csv)['trades_imported']==1
        db.info['tenant_id']=second
        assert svc.import_ibkr_csv(db,csv)['trades_imported']==1
        assert svc.import_ibkr_csv(db,csv)['duplicate_trades']==1
        db.info['tenant_id']=first
        assert svc.import_ibkr_csv(db,csv)['duplicate_trades']==1


def test_csv_savepoint_rolls_back_failed_position_and_keeps_other_rows(monkeypatch):
    from app.services.portfolio_ledger_service import PortfolioLedgerService
    engine = create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    with _tenant_session(engine) as db:
        # A row failure after a rebuild must not leave a phantom position.
        original=PortfolioLedgerService.create_transaction
        calls=[]
        def racing(self, db, **kwargs):
            row=original(self,db,**kwargs);calls.append(row)
            if len(calls)==1: raise ValueError('isolated invalid row after rebuild')
            return row
        monkeypatch.setattr(PortfolioLedgerService,'create_transaction',racing)
        csv='symbol,action,quantity,price,date\n'+f'AAPL,buy,1,10,{date.today().isoformat()}\nMSFT,buy,2,20,{date.today().isoformat()}\n'
        r=IBKRImportService().import_ibkr_csv(db,csv)
        assert r['trades_imported']==1 and r['rows_skipped']==1
        assert db.query(Transaction).count()==1
        assert db.query(Position).count()==1


def test_csv_no_id_explains_partial_file_ambiguity():
    engine = create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    with _tenant_session(engine) as db:
        csv=f'symbol,action,quantity,price,date\nAAPL,buy,1,10,{date.today().isoformat()}\n'
        r=IBKRImportService().import_ibkr_csv(db,csv)
        assert 'archivos parciales' in r['identity_warning'] and 'tradeID' in r['identity_warning']
