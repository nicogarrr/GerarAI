"""Finnhub profile validation and Redis factory contracts, without external I/O."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import redis

from app.core import redis_retry
from app.services.connectors import finnhub


def test_redis_factory_skips_empty_url(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(redis, "from_url", factory)
    monkeypatch.setattr(finnhub, "get_settings", lambda: SimpleNamespace(redis_url=""))
    assert finnhub._finnhub_redis_client() is None
    factory.assert_not_called()


def test_redis_factory_preserves_bounded_timeouts_and_no_retry(monkeypatch):
    connection = object()
    retry = object()
    factory = Mock(return_value=connection)
    monkeypatch.setattr(redis, "from_url", factory)
    monkeypatch.setattr(redis_retry, "no_retry", lambda: retry)
    monkeypatch.setattr(finnhub, "get_settings", lambda: SimpleNamespace(redis_url="redis://local.test/9"))
    assert finnhub._finnhub_redis_client() is connection
    factory.assert_called_once_with(
        "redis://local.test/9", socket_connect_timeout=0.5, socket_timeout=1.0, retry=retry
    )


def test_redis_factory_failure_returns_none_for_pacer_fallback(monkeypatch):
    factory = Mock(side_effect=ValueError("bad connection configuration"))
    monkeypatch.setattr(redis, "from_url", factory)
    monkeypatch.setattr(finnhub, "get_settings", lambda: SimpleNamespace(redis_url="redis://local.test/9"))
    assert finnhub._finnhub_redis_client() is None
    factory.assert_called_once()


def test_blocked_for_returns_shared_pacer_value(monkeypatch):
    pacer = Mock()
    pacer.blocked_for.return_value = 12.75
    monkeypatch.setattr(finnhub, "_pacer", pacer)
    assert finnhub.finnhub_blocked_for() == 12.75
    pacer.blocked_for.assert_called_once_with()
    finnhub.reset_finnhub_pacer()
    pacer.reset.assert_called_once_with()


@pytest.mark.parametrize("payload", [{"name": "Example", "ticker": "AAPL"}, {}, [], None, "invalid"])
def test_profile_http_shape_validation_and_health(monkeypatch, payload):
    original_client = httpx.AsyncClient
    registry = Mock()
    pacer = Mock(wait=AsyncMock())
    options = []
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "finnhub.io"
        assert request.url.path == "/api/v1/stock/profile2"
        assert dict(request.url.params) == {"symbol": "AAPL", "token": "synthetic-test-key"}
        return httpx.Response(200, content=json.dumps(payload), headers={"Content-Type": "application/json"})

    def factory(**kwargs):
        options.append(kwargs)
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(finnhub.httpx, "AsyncClient", factory)
    monkeypatch.setattr(
        finnhub, "get_settings", lambda: SimpleNamespace(finnhub_api_key="synthetic-test-key")
    )
    monkeypatch.setattr(finnhub, "get_data_source_registry", lambda: registry)
    monkeypatch.setattr(finnhub, "_pacer", pacer)
    client = finnhub.FinnhubClient()
    if isinstance(payload, dict):
        assert asyncio.run(client.profile("aapl")) == payload
        registry.record_success.assert_called_once_with("finnhub")
        registry.record_failure.assert_not_called()
    else:
        with pytest.raises(RuntimeError, match="invalid profile"):
            asyncio.run(client.profile("aapl"))
        registry.record_failure.assert_called_once_with("finnhub", "profile no objeto (parse failed)")
        registry.record_success.assert_not_called()
    assert options == [{"timeout": 30}]
    assert len(requests) == 1
    pacer.wait.assert_awaited_once_with()
    pacer.cool_down.assert_not_called()


@pytest.mark.parametrize("payload", [{}, None, "not a list"])
def test_symbol_universe_rejects_non_list_without_success(monkeypatch, payload):
    registry = Mock()
    fetch = AsyncMock(return_value=payload)
    monkeypatch.setattr(finnhub, "get_data_source_registry", lambda: registry)
    monkeypatch.setattr(finnhub.FinnhubClient, "_get", fetch)
    with pytest.raises(RuntimeError, match="invalid symbol universe"):
        asyncio.run(finnhub.FinnhubClient().us_symbols())
    fetch.assert_awaited_once_with("/stock/symbol", {"exchange": "US"})
    registry.record_failure.assert_called_once_with("finnhub", "universo de símbolos no lista (parse failed)")
    registry.record_success.assert_not_called()
