"""OpenCode free-tier 502 is deterministic: no retries, short circuit breaker, periodic re-probe."""

import asyncio

import httpx
import pytest

from app.llm import base
from app.llm.adapters import OpenAICompatibleProvider
from app.llm.errors import ProviderHTTPError

BODY = '{"error":{"message":"OpenCode\'s free tier can only be used from within OpenCode"}}'


IP_BLOCK_BODY = (
    '{"type": "error", "error": {"type": "RuntimeError", "message": "serve error: {\\"name\\": \\"APIError\\", '
    '\\"data\\": {\\"message\\": \\"OpenCode\'s free models aren\'t available from your current network '
    'because we\'ve detected abusive traffic from this IP address.\\"}}"}}'
)


@pytest.fixture(autouse=True)
def _clean():
    base._free_tier_breaker.clear()
    yield
    base._free_tier_breaker.clear()


def _provider(handler):
    return OpenAICompatibleProvider(
        api_key="k", base_url="https://example.test/v1", default_model="m", provider_name="opencode-go",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), max_retries=2,
    )


def _post(provider, model="m"):
    return asyncio.run(provider._post_json("https://example.test/v1/chat/completions", headers={}, payload={"model": model}))


def test_free_tier_502_is_not_retried_and_opens_breaker():
    calls = []
    p = _provider(lambda r: (calls.append(1), httpx.Response(502, text=BODY))[1])
    with pytest.raises(ProviderHTTPError) as e:
        _post(p)
    assert e.value.status_code == 502 and len(calls) == 1
    with pytest.raises(ProviderHTTPError):
        _post(p)
    assert len(calls) == 1  # breaker open: no new request


def test_breaker_is_per_model_and_reprobes_after_expiry():
    calls = []
    p = _provider(lambda r: (calls.append(1), httpx.Response(502, text=BODY))[1])
    with pytest.raises(ProviderHTTPError):
        _post(p, "a")
    with pytest.raises(ProviderHTTPError):
        _post(p, "b")
    assert len(calls) == 2
    base._free_tier_breaker[("opencode-go", "a")] = 0.0
    with pytest.raises(ProviderHTTPError):
        _post(p, "a")
    assert len(calls) == 3


def test_recovery_after_reprobe_succeeds():
    ok = {"choices": [{"message": {"content": "hi"}}]}
    state = {"fail": True}
    p = _provider(lambda r: httpx.Response(502, text=BODY) if state["fail"] else httpx.Response(200, json=ok))
    with pytest.raises(ProviderHTTPError):
        _post(p)
    state["fail"] = False
    base._free_tier_breaker[("opencode-go", "m")] = 0.0
    assert _post(p).status_code == 200


def test_other_502_and_5xx_keep_ordinary_retries(monkeypatch):
    async def nosleep(_): return None
    monkeypatch.setattr(base.asyncio, "sleep", nosleep)
    calls = []
    p = _provider(lambda r: (calls.append(1), httpx.Response(502, text="bad gateway"))[1])
    with pytest.raises(ProviderHTTPError):
        _post(p)
    assert len(calls) == 3 and not base._free_tier_breaker


def test_ip_block_502_is_not_retried_and_opens_breaker():
    calls = []
    p = _provider(lambda r: (calls.append(1), httpx.Response(502, text=IP_BLOCK_BODY))[1])
    with pytest.raises(ProviderHTTPError):
        _post(p)
    assert len(calls) == 1 and ("opencode-go", "m") in base._free_tier_breaker
    with pytest.raises(ProviderHTTPError):
        _post(p)
    assert len(calls) == 1
