"""A conflicting duplicate ticker must not publish whichever weight came first."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models.entities import EtfHolding
from app.services import etf_holdings as eh
from tests.test_etf_holdings import _client, db  # noqa: F401
from tests.test_etf_holdings_bordes import NASA_PAGE, UFO_CSV_URL, UFO_HTML, UFO_PAGE, _procure_csv


@pytest.mark.parametrize('first,second', [('1', '8'), ('8', '1')])
def test_conflicting_duplicate_weight_keeps_previous_snapshot(db, first, second):
    db.add(EtfHolding(etf='UFO', ticker='KEEP', weight_pct=3,
        as_of=date(2026, 10, 15), source_url='old'))
    db.commit()
    csv = _procure_csv([first] + ['1'] * 9) + f'10/19/2026,UFO,TA,x,N,1,1,1,{second}%\n'
    result = eh.refresh_etf_holdings(db, _client({UFO_PAGE: UFO_HTML, UFO_CSV_URL: csv, NASA_PAGE: ''}))
    assert result['UFO'] == 'pesos duplicados contradictorios: se conserva la carga anterior'
    rows = db.scalars(select(EtfHolding).where(EtfHolding.etf == 'UFO')).all()
    assert [(r.ticker, r.as_of) for r in rows] == [('KEEP', date(2026, 10, 15))]
