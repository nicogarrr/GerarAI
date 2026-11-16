"""Monitor split windows: actual SQL/ORM counters, no timing thresholds."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes import watchlist
from app.models import Company, CorporateAction, MarketPrice
from app.models.entities import Base


@pytest.mark.parametrize("count,history", [(1,30),(20,30),(60,300)])
def test_split_monitor_reads_have_constant_query_and_load_budgets(monkeypatch,count,history):
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    today=date.today()
    with Session(engine,expire_on_commit=False) as db:
        for index in range(count):
            c=Company(ticker=f'SPLITPERF{index}',name='Fixture',exchange='NYSE',currency='USD',company_type='listed',valuation_model='dcf')
            db.add(c);db.flush()
            db.add(CorporateAction(company_id=c.id,action_type='reverse_split',effective_date=today-timedelta(days=5),ratio=Decimal('.1')))
            for age in range(history):
                db.add(MarketPrice(company_id=c.id,date=today-timedelta(days=age),close=Decimal(100+age)))
        db.commit();db.expunge_all()
        monkeypatch.setattr(watchlist,'resolve_fair_values',lambda db,companies:{c.id:{'value':None,'thesis_version':None,'source':None,'label':None,'as_of':None,'publishable':False} for c in companies})
        statements=[];loaded=[]
        event.listen(engine,'before_cursor_execute',lambda *args:statements.append(args[2]))
        def on_load(obj,ctx): loaded.append(obj.id)
        event.listen(MarketPrice,'load',on_load)
        try:
            result=watchlist.watchlist_monitor(tickers=','.join(f'SPLITPERF{i}' for i in range(count)),db=db)
        finally:
            event.remove(MarketPrice,'load',on_load)
        assert len(result['items'])==count
        for row in result['items'].values():
            assert row['low_52w']==100 and row['low_52w_sessions']==6
        print(f'COUNTERS split{count} history{history} statements={len(statements)} MarketPrice_loads={len(loaded)}')
        assert len(statements)<=8
        assert len(loaded)<=3*count


def test_split_windows_stay_per_company_and_ignore_old_future_events(monkeypatch):
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    today=date.today()
    with Session(engine) as db:
        cases=[('TWO', [8,2], [(9,1),(4,20),(1,40)],40,1),
               ('FIVE',[5],[(9,1),(4,20),(1,40)],20,2),
               ('EMPTY',[2],[(9,1),(4,20)],None,0),
               ('OUTSIDE',[400,-3],[(9,1),(4,20)],1,2)]
        for ticker,events,prices,expected,count in cases:
            c=Company(ticker=ticker,name=ticker,exchange='NYSE',currency='USD',company_type='listed',valuation_model='dcf')
            db.add(c);db.flush()
            for age in events:db.add(CorporateAction(company_id=c.id,action_type='split',effective_date=today-timedelta(days=age),ratio=2))
            for age,price in prices:db.add(MarketPrice(company_id=c.id,date=today-timedelta(days=age),close=price))
            db.add(MarketPrice(company_id=c.id,date=today,close=0))
        db.commit();db.expunge_all()
        monkeypatch.setattr(watchlist,'resolve_fair_values',lambda db,companies:{c.id:{'value':None,'thesis_version':None,'source':None,'label':None,'as_of':None,'publishable':False} for c in companies})
        out=watchlist.watchlist_monitor(tickers=','.join(c[0] for c in cases),db=db)['items']
        for ticker,events,prices,expected,count in cases:
            assert out[ticker]['low_52w']==expected
            assert out[ticker]['low_52w_sessions']==count
