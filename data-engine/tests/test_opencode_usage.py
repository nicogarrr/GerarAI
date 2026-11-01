"""Cuota OpenCode: parsing de Retry-After, consulta /usage y breaker reset-aware."""
import asyncio
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from functools import wraps

import httpx
import pytest

from app.llm import base
from app.llm.adapters import OpenAICompatibleProvider
from app.llm.contracts import LLMRequest, Message
from app.llm.errors import ProviderHTTPError
from app.llm.opencode_usage import MAX_RETRY_AFTER_SECONDS, fetch_go_usage, parse_retry_after


def run_async(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapped


def test_parse_retry_after_seconds():
    assert parse_retry_after("84607") == 84607.0
    assert parse_retry_after(" 12 ") == 12.0
    assert parse_retry_after("0") == 0.0


def test_parse_retry_after_http_date():
    future = datetime.now(UTC) + timedelta(seconds=600)
    value = parse_retry_after(format_datetime(future, usegmt=True))
    assert value is not None and 550 < value <= 600
    past = datetime.now(UTC) - timedelta(seconds=60)
    assert parse_retry_after(format_datetime(past, usegmt=True)) is None


def test_parse_retry_after_garbage_and_clamp():
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("no es una fecha") is None
    assert parse_retry_after("-5") is None
    assert parse_retry_after(str(10 * 24 * 3600)) == MAX_RETRY_AFTER_SECONDS


@run_async
async def test_fetch_go_usage_ok():
    payload = {"usage": {"weekly": {"status": "ok", "percent": 12, "resetsAt": "2026-11-02T00:00:00.000Z"}}}

    def handler(req):
        assert req.url.path == "/zen/go/v1/usage"
        assert req.headers["authorization"] == "Bearer k"
        assert req.headers["x-opencode-session"] == "s"
        return httpx.Response(200, json=payload)

    original = httpx.AsyncClient
    httpx.AsyncClient = lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    try:
        assert await fetch_go_usage("https://opencode.ai/zen/go/v1", "k", session="s") == payload
    finally:
        httpx.AsyncClient = original


@run_async
async def test_fetch_go_usage_degrades_to_none():
    def handler(req):
        return httpx.Response(404)

    original = httpx.AsyncClient
    httpx.AsyncClient = lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    try:
        assert await fetch_go_usage("https://opencode.ai/zen/v1", "k") is None
    finally:
        httpx.AsyncClient = original
    assert await fetch_go_usage("", "k") is None
    assert await fetch_go_usage("https://opencode.ai/zen/go/v1", " ") is None


@run_async
async def test_quota_429_honors_retry_after_and_blocks_until_reset():
    """429 de cuota con Retry-After: breaker abierto hasta el reset, sin re-sondeo."""
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(
            429,
            json={"error": {"message": "GoUsageLimitError: weekly usage limit reached"}},
            headers={"Retry-After": "3600"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            api_key="k", base_url="https://go.invalid/v1",
            default_model="deepseek-v4.1-flash", provider_name="opencode-go-subscription",
            max_retries=0, client=client,
        )
        provider.interactive_quota_breaker = True
        req = LLMRequest([Message("user", "hola")], task="chat")
        with pytest.raises(ProviderHTTPError) as first:
            await provider.complete(req)
        assert first.value.status_code == 429
        assert len(calls) == 1
        # Segundo intento: el breaker contesta sin red, hasta dentro de ~1 h.
        with pytest.raises(ProviderHTTPError):
            await provider.complete(req)
        assert len(calls) == 1
        snapshot = base.breaker_snapshot()
        entry = next(b for b in snapshot if b["provider"] == "opencode-go-subscription")
        assert 3500 < entry["seconds_remaining"] <= 3600
        assert entry["until"] > time.time() + 3500


@run_async
async def test_quota_429_without_retry_after_keeps_short_probe_cooldown():
    def handler(req):
        return httpx.Response(429, json={"error": {"message": "weekly quota exhausted"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            api_key="k", base_url="https://go.invalid/v1",
            default_model="deepseek-v4.1-flash", provider_name="opencode-go-subscription",
            max_retries=0, client=client,
        )
        provider.interactive_quota_breaker = True
        with pytest.raises(ProviderHTTPError):
            await provider.complete(LLMRequest([Message("user", "hola")], task="chat"))
        entry = next(b for b in base.breaker_snapshot() if b["provider"] == "opencode-go-subscription")
        assert entry["seconds_remaining"] <= 120
