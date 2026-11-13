"""A missing equity date must not silently turn a partial file into a full load."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models.entities import EtfHolding
from app.services import etf_holdings as eh
from tests.test_etf_holdings import PROCURE, TEMA, _client, db  # noqa: F401


@pytest.mark.parametrize(('etf', 'parser', 'csv', 'stamp', 'url'), [
    ('UFO', eh.parse_procure, PROCURE, '10/19/2026', 'https://procureetfs.com/x/UFO-Holdings-invalid.csv'),
    ('NASA', eh.parse_tema, TEMA, '2026-10-16', 'https://temaetfs.com/h/NASA-holdings-99999999.csv'),
])
@pytest.mark.parametrize('bad_date', ['', 'bad', '2026-99-99'])
def test_invalid_equity_date_keeps_previous_snapshot(db, etf, parser, csv, stamp, url, bad_date):
    lines = csv.splitlines()
    # Eleven equity rows: dropping one would still pass the ten-row threshold.
    lines[-2] = lines[-2].replace(stamp, bad_date)
    broken = '\n'.join(lines)
    with pytest.raises(ValueError, match='equity date'):
        parser(broken)
    db.add(EtfHolding(etf=etf, ticker='KEEP', weight_pct=3,
                      as_of=date(2026, 10, 15), source_url='old'))
    db.commit()
    result = eh.refresh_etf_holdings(db, _client({eh.SOURCES[etf].page: f'<a href="{url}">', url: broken}))
    assert 'ningun fichero valido' in result[etf]
    assert [row.ticker for row in db.scalars(select(EtfHolding).where(EtfHolding.etf == etf))] == ['KEEP']
