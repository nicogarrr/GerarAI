"""EIA con JSON ilegible degrada a N/D, no rompe la página de flujos."""
from types import SimpleNamespace

import pytest

from app.services import energy_flows as energy
from app.services.money_flows import FLOW_THEMES


@pytest.mark.parametrize('payload', [None, [], {'response': None}, {'response': []},
                                      {'response': {'data': {}}}, {'response': {'data': {'error': 'bad'}}}, {'response': {'data': [None]}},
                                      {'response': {'data': ['ilegible']}}])
def test_invalid_payload_is_unavailable_without_a_fake_zero(monkeypatch, payload):
    monkeypatch.setattr(energy, '_cache', {})
    monkeypatch.setattr(energy, 'get_settings', lambda: SimpleNamespace(eia_api_key='fixture-key'))
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(energy.httpx, 'get', lambda *a, **kw: response)
    out = energy.build_energy_flow(FLOW_THEMES['utilities'])
    assert out['spenders'] == []
    assert out['spenders_total'] is None
    assert out['destinations'] == []
    assert out['suppliers'] == []
    assert out['notes'] and 'N/D' in out['notes'][0]
    assert energy._cache['failed_until'] > 0
    assert 'fixture-key' not in str(out)
