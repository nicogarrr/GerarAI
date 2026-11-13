"""Holdings of different dates cannot be stamped with the newest date."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models.entities import EtfHolding
from app.services import etf_holdings as eh
from tests.test_etf_holdings import PROCURE, TEMA, _client, db  # noqa: F401


@pytest.mark.parametrize(('parser', 'csv', 'old', 'new'), [
    (eh.parse_procure, PROCURE, '10/19/2026', '10/20/2026'),
    (eh.parse_tema, TEMA, '2026-10-16', '2026-10-17'),
])
def test_mixed_dates_are_not_merged_as_one_snapshot(parser, csv, old, new):
    # Replace an equity row, not cash/unlisted rows excluded by the parser.
    lines = csv.splitlines()
    lines[-2] = lines[-2].replace(old, new)
    with pytest.raises(ValueError, match='mixed snapshot dates'):
        parser('\n'.join(lines))


@pytest.mark.parametrize(('etf', 'csv', 'old', 'new', 'url'), [
    ('UFO', PROCURE, '10/19/2026', '10/20/2026', 'https://procureetfs.com/x/UFO-Holdings-mixed.csv'),
    ('NASA', TEMA, '2026-10-16', '2026-10-17', 'https://temaetfs.com/h/NASA-holdings-99999999.csv'),
])
def test_mixed_file_keeps_previous_snapshot(db, etf, csv, old, new, url):
    lines = csv.splitlines()
    lines[-2] = lines[-2].replace(old, new)
    db.add(EtfHolding(etf=etf, ticker='KEEP', weight_pct=3, as_of=date(2026, 10, 15), source_url='old'))
    db.commit()
    result = eh.refresh_etf_holdings(db, _client({eh.SOURCES[etf].page: f'<a href="{url}">', url: '\n'.join(lines)}))
    assert 'ningun fichero valido' in result[etf]
    rows = db.scalars(select(EtfHolding).where(EtfHolding.etf == etf)).all()
    assert [(r.ticker, r.as_of) for r in rows] == [('KEEP', date(2026, 10, 15))]
