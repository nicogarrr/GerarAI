"""Repeated CSV rows do not prove a complete ETF holdings file."""
from datetime import date

from sqlalchemy import select

from app.models.entities import EtfHolding
from app.services import etf_holdings as eh
from tests.test_etf_holdings import _client, db  # noqa: F401
from tests.test_etf_holdings_bordes import NASA_PAGE, UFO_CSV_URL, UFO_HTML, UFO_PAGE


def test_ten_rows_of_one_ticker_do_not_replace_complete_load(db):
    db.add(EtfHolding(etf='UFO', ticker='KEEP', weight_pct=3,
        as_of=date(2026, 10, 15), source_url='old'))
    db.commit()
    csv = ('Date,Account,StockTicker,CUSIP,SecurityName,Shares,Price,MarketValue,Weightings\n'
        + '10/19/2026,UFO,ONE,x,N,1,1,1,1%\n' * eh.MIN_ROWS)
    result = eh.refresh_etf_holdings(db, _client({UFO_PAGE: UFO_HTML, UFO_CSV_URL: csv, NASA_PAGE: ''}))
    assert 'ningun fichero valido' in result['UFO']
    rows = db.scalars(select(EtfHolding).where(EtfHolding.etf == 'UFO')).all()
    assert [r.ticker for r in rows] == ['KEEP']
