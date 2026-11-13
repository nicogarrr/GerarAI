"""Future-dated ETF snapshots are neither ingested nor served as current."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models.entities import EtfHolding
from app.services import etf_holdings as eh
from tests.test_etf_holdings import PROCURE, TEMA, _client, db  # noqa: F401


@pytest.mark.parametrize(('etf', 'csv', 'url'), [
    ('UFO', PROCURE, 'https://procureetfs.com/x/UFO-Holdings-future.csv'),
    ('NASA', TEMA, 'https://temaetfs.com/h/NASA-holdings-99999999.csv'),
])
def test_future_file_does_not_replace_existing_snapshot(db, etf, csv, url):
    current = date.today()
    future_year = current.year + 1
    csv = csv.replace('2026', str(future_year))
    db.add(EtfHolding(etf=etf, ticker='KEEP', weight_pct=3, as_of=current, source_url='old'))
    db.commit()
    result = eh.refresh_etf_holdings(db, _client({eh.SOURCES[etf].page: f'<a href="{url}">', url: csv}))
    assert 'ningun fichero valido' in result[etf]
    stored = db.scalars(select(EtfHolding).where(EtfHolding.etf == etf)).all()
    assert [(r.ticker, r.as_of) for r in stored] == [('KEEP', current)]


def test_lookup_accepts_today_and_age_boundary_but_not_future(db):
    today = date(2026, 11, 13)
    for ticker, days in [('NOW', 0), ('EDGE', -eh.MAX_AGE_DAYS), ('OLD', -eh.MAX_AGE_DAYS - 1), ('FUT', 1)]:
        db.add(EtfHolding(etf='UFO', ticker=ticker, weight_pct=3,
            as_of=today + timedelta(days=days), source_url='test'))
    db.flush()
    result = eh.etfs_for_tickers(db, {'NOW', 'EDGE', 'OLD', 'FUT'}, today=today)
    assert set(result) == {'NOW', 'EDGE'}
