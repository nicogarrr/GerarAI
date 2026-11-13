"""Expected and actual pricing dates must not be interchanged."""
import pytest

from app.services.connectors.ipo_calendar import normalize_ipo_row


@pytest.mark.parametrize('status,expected', [('priced', '2026-10-23'), ('upcoming', '2026-10-30')])
def test_status_selects_its_own_date_when_both_present(status, expected):
    event = normalize_ipo_row({'pricedDate': '10/23/2026', 'expectedPriceDate': '10/30/2026'}, status)
    assert event['date'] == expected


@pytest.mark.parametrize('status,row', [('priced', {'expectedPriceDate': '10/30/2026'}),
    ('upcoming', {'pricedDate': '10/23/2026'})])
def test_missing_date_for_status_is_unknown_not_other_kind(status, row):
    assert normalize_ipo_row(row, status)['date'] is None
