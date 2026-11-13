"""An absent USAspending breakdown must not look like a confirmed empty top."""
import pytest

from app.services import money_flows as service


@pytest.mark.parametrize('fetch', [service.fetch_top_categories, service.fetch_top_recipients])
@pytest.mark.parametrize('payload', [{}, {'error': 'not available'}, {'results': None}, {'results': {}}])
def test_missing_breakdown_is_unavailable(fetch, payload, monkeypatch):
    monkeypatch.setattr(service, '_usaspending_post', lambda *_: payload)
    with pytest.raises(ValueError, match='USAspending'):
        fetch('Department of Defense', '2024-10-01', '2025-09-30')


@pytest.mark.parametrize('fetch', [service.fetch_top_categories, service.fetch_top_recipients])
def test_explicit_empty_results_remain_valid(fetch, monkeypatch):
    monkeypatch.setattr(service, '_usaspending_post', lambda *_: {'results': []})
    assert fetch('Department of Defense', '2024-10-01', '2025-09-30') == []
