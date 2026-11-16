"""Cold requests must not wait on background completion, even offline."""
from types import SimpleNamespace
from unittest.mock import Mock

from app.api.routes import screeners


def test_cold_offline_never_waits_for_background_result(monkeypatch):
    future = Mock()
    future.done.return_value = False
    def reject_wait(*args, **kwargs):
        raise AssertionError('request waited on background work')
    future.result.side_effect = reject_wait
    monkeypatch.setattr(screeners, 'get_settings', lambda: SimpleNamespace(
        finnhub_api_key='', screener_quote_vendor='offline', is_production=False))
    monkeypatch.setattr(screeners, '_schedule_real_refresh', lambda *a, **kw: future)
    monkeypatch.setattr(screeners, '_real_response_cache', {})
    monkeypatch.setattr(screeners, '_real_items_cache', {})
    result = screeners.real_time_screener(db=SimpleNamespace(info={'tenant_id': 987}))
    assert result['screener'] == [] and result['refreshing'] is True
    future.result.assert_not_called()


def test_cold_reread_does_not_adopt_another_vendors_bucket(monkeypatch):
    future = Mock()
    future.done.return_value = False
    monkeypatch.setattr(screeners, 'get_settings', lambda: SimpleNamespace(
        finnhub_api_key='configured', screener_quote_vendor='finnhub', is_production=False))
    monkeypatch.setattr(screeners, '_schedule_real_refresh', lambda *a, **kw: future)
    monkeypatch.setattr(screeners, '_real_response_cache', {})
    monkeypatch.setattr(screeners, '_real_items_cache', {987: {
        'items': [{'symbol': 'ASTS', 'price': 50, 'marketCap': 1000}],
        'vendor': 'yahoo', 'at_wall': 100.0,
    }})
    result = screeners.real_time_screener(db=SimpleNamespace(info={'tenant_id': 987}))
    assert result['screener'] == []
    assert result['refreshing'] is True
    future.result.assert_not_called()
