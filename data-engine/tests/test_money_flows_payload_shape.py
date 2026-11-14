"""Malformed upstream rows must reach the existing unavailable notice."""
from types import SimpleNamespace

import pytest

from app.services import money_flows as flows


@pytest.mark.parametrize('endpoint', ['obligations', 'categories', 'recipients'])
@pytest.mark.parametrize('payload', [None, [], {'results': None}, {'results': {}},
                                     {'results': {'bad': 'row'}}, {'results': [None]},
                                     {'results': ['bad']}])
def test_malformed_usaspending_response_reaches_unavailable_notice(monkeypatch, endpoint, payload):
    monkeypatch.setattr(flows, '_cache', {})
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(flows.httpx, 'post', lambda *a, **kw: response)
    if endpoint != 'obligations':
        monkeypatch.setattr(flows, 'fetch_agency_obligations', lambda *a: 100.0)
    if endpoint == 'recipients':
        monkeypatch.setattr(flows, 'fetch_top_categories', lambda *a: [])
    spenders, destinations, suppliers, _, notes, _, _ = flows.build_usaspending_theme(flows.FLOW_THEMES['defensa'])
    assert notes and 'no disponible' in notes[0]
    assert spenders[0]['amount'] == (None if endpoint == 'obligations' else 100.0)
    assert destinations == []
    assert suppliers == []
    assert 'fail:Department of Defense' in flows._cache
