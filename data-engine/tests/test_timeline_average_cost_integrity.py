"""The chart cannot average costs in different currencies as one price."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.services import company_events_service as svc


class DB:
    info = {'tenant_id': 'test'}

    def __init__(self, positions):
        self.positions = positions

    def scalars(self, query):
        return SimpleNamespace(all=lambda: self.positions)


def position(qty=10, cost=100, currency='USD'):
    return SimpleNamespace(quantity=qty, average_cost=cost, currency=currency)


@pytest.mark.parametrize('positions', [
    [position(), position(currency='EUR')],
    [position(currency='EUR')], [position(currency=None)],
    [position(), position(cost=None)], [position(), position(cost=float('nan'))],
    [position(), position(cost=0)], [position(), position(qty=float('nan'))],
])
def test_incomparable_or_incomplete_cost_is_unknown_but_start_is_retained(monkeypatch, positions):
    monkeypatch.setattr(svc, 'current_holding_starts', lambda *args: {1: date(2024, 1, 2)})
    result = svc.stored_holding(DB(positions), SimpleNamespace(id=1, currency='USD'))
    assert result['average_cost'] is None
    assert result['first_buy_date'] == '2024-01-02'
    assert result['notice']


def test_minor_currency_units_are_not_silently_treated_as_major(monkeypatch):
    monkeypatch.setattr(svc, 'current_holding_starts', lambda *args: {})
    result = svc.stored_holding(DB([position(currency='GBp')]), SimpleNamespace(id=1, currency='GBP'))
    assert result['average_cost'] is None
    assert result['notice']


def test_same_known_currency_still_computes_weighted_cost(monkeypatch):
    monkeypatch.setattr(svc, 'current_holding_starts', lambda *args: {})
    result = svc.stored_holding(DB([position(), position(qty=30, cost=120, currency='usd')]),
                                SimpleNamespace(id=1, currency='USD'))
    assert result == {'average_cost': 115, 'first_buy_date': None}
