"""A known subtotal is not the full filed value of all buyers."""
from types import SimpleNamespace

import pytest

from app.schemas.api import MostBoughtOut
from app.services import investors as svc


@pytest.mark.parametrize('values,expected,known,missing', [
    ([None, 100], None, 100, 1), ([None, None], None, 0, 2),
    ([0, 0], 0, 0, 0), ([100, 200], 300, 300, 0),
])
def test_buyer_values_are_complete_or_explicit_subtotals(monkeypatch, values, expected, known, missing):
    monkeypatch.setattr(svc, '_reviewed_managers', lambda db: {
        inv.cik: SimpleNamespace(coverage='ok') for inv in svc.INVESTORS if inv.cik in svc.REVIEWED_MANAGERS
    })
    ciks = [inv.cik for inv in svc.INVESTORS if inv.cik in svc.REVIEWED_MANAGERS][:len(values)]

    def changes(self, db, *, cik):
        if cik not in ciks:
            return {'status': 'insufficient_history'}
        return {'status': 'ok', 'latest_report': '2026-06-30', 'changes': [{
            'cusip': '037833100', 'name_of_issuer': 'Example', 'put_call': None,
            'change': 'increased', 'value_usd_thousands_latest': values[ciks.index(cik)],
        }]}

    monkeypatch.setattr(svc.ManagerHoldingIngestionService, 'changes', changes)
    monkeypatch.setattr('app.services.instrument_reference.names_by_cusip', lambda *args: {})
    result = svc.most_bought(None)
    item = result['items'][0]
    assert item['buyers_count'] == len(values)
    assert item['value_usd'] == expected
    assert item['known_value_usd'] == known
    assert item['missing_value_count'] == missing
    assert bool(item['notice']) == bool(missing)
    MostBoughtOut.model_validate(result)
