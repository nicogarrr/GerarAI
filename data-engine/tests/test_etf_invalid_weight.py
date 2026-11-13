"""Invalid equity weights cannot be persisted as plausible holdings."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models.entities import EtfHolding
from app.services import etf_holdings as eh
from tests.test_etf_holdings import _client, db  # noqa: F401
from tests.test_etf_holdings_bordes import NASA_PAGE, UFO_CSV_URL, UFO_HTML, UFO_PAGE, _procure_csv


@pytest.mark.parametrize('weight', ['-1', 'Infinity', 'NaN', '101'])
def test_invalid_equity_weight_keeps_prior_load(db, weight):
    db.add(EtfHolding(etf='UFO', ticker='KEEP', weight_pct=3,
        as_of=date(2026, 10, 15), source_url='old'))
    db.commit()
    result = eh.refresh_etf_holdings(db, _client({UFO_PAGE: UFO_HTML,
        UFO_CSV_URL: _procure_csv([weight] + ['1'] * 10), NASA_PAGE: ''}))
    assert 'ningun fichero valido' in result['UFO']
    rows = db.scalars(select(EtfHolding).where(EtfHolding.etf == 'UFO')).all()
    assert [r.ticker for r in rows] == ['KEEP']


@pytest.mark.parametrize('fraction,raw', [(False, '-1'), (False, 'Infinity'), (False, 'NaN'), (False, '101'), (True, '1.01')])
def test_pct_rejects_nonfinite_or_out_of_range(fraction, raw):
    assert eh._pct(raw, fraction=fraction) is None


def test_tema_equity_invalid_fraction_rejects_file():
    from tests.test_etf_holdings import TEMA

    with pytest.raises(ValueError, match='invalid equity weight'):
        eh.parse_tema(TEMA.replace(',0.055,', ',NaN,'))


@pytest.mark.parametrize('fraction,raw,expected', [(False, '0', 0), (False, '100', 100), (True, '1', 100)])
def test_pct_preserves_real_boundary_values(fraction, raw, expected):
    assert eh._pct(raw, fraction=fraction) == expected
