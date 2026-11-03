import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx
import pytest

from app.core.config import Settings
from app.llm import LLMRequest, Message, create_llm_provider
from app.llm import thesis_inference_quota as q
from app.llm.errors import LLMError

URL = "https://opencode.ai/zen/go/v1/chat/completions"
PAYLOAD = {"model": q.MODEL, "max_tokens": 700}


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.counts = {}

    def eval(self, script, nkeys, key, global_key, enabled_key, cap, global_cap):
        assert script == q._SCRIPT and nkeys == 3 and enabled_key == q.ENABLED_KEY
        with self.lock:
            if self.counts.get(enabled_key) == "0":
                return -1
            n = self.counts.get(key, 0)
            g = self.counts.get(global_key, 0)
            if n >= cap or g >= global_cap:
                return 0
            self.counts[key] = n + 1
            self.counts[global_key] = g + 1
            return n + 1



@pytest.fixture
def store(monkeypatch):
    store = Store()
    monkeypatch.setattr("app.core.cache._redis_client", lambda: store)
    return store


def test_scope_is_feature_only_and_restores_even_on_failure(store):
    for _ in range(30):
        q.reserve_request("https://other.example/api", {})
    assert not store.counts
    with pytest.raises(q.ThesisInferenceQuotaError), q.scope(2):
        q.reserve_request("https://generativelanguage.googleapis.com/v1", PAYLOAD)
    q.reserve_request("https://other.example/api", {})
    assert not store.counts


@pytest.mark.parametrize("url,payload", [
    ("https://opencode.ai/zen/v1/chat/completions", PAYLOAD),
    ("http://opencode.ai/zen/go/v1/chat/completions", PAYLOAD),
    ("https://opencode.ai.evil.test/zen/go/v1/chat/completions", PAYLOAD),
    (URL, {"model": "gemini-3.5-flash-lite", "max_tokens": 700}),
    (URL, {"model": q.MODEL, "max_tokens": 701}),
])
def test_only_go_approved_before_counter_or_network(store, url, payload):
    with q.scope(14), pytest.raises(q.ThesisInferenceQuotaError):
        q.reserve_request(url, payload)
    assert not store.counts


def test_concurrent_attempts_atomic_shared_daily_tenant_cap(store):
    def call(_):
        try:
            with q.scope(2):
                q.reserve_request(URL, PAYLOAD)
            return 1
        except q.ThesisInferenceQuotaError:
            return 0
    with ThreadPoolExecutor(max_workers=20) as pool:
        assert sum(pool.map(call, range(80))) == 10
    with q.scope(3):
        q.reserve_request(URL, PAYLOAD)
    assert sorted(store.counts.values()) == [1, 10, 11]


def test_utc_day_and_tenant_are_separate(store):
    for _ in range(10):
        q._reserve(2, datetime(2026, 11, 3, 23, 59, tzinfo=UTC))
    with pytest.raises(q.ThesisInferenceQuotaError):
        q._reserve(2, datetime(2026, 11, 3, 23, 59, tzinfo=UTC))
    q._reserve(2, datetime(2026, 11, 4, tzinfo=UTC))
    assert len(store.counts) == 4


def test_redis_unavailable_fails_closed_only_in_feature(monkeypatch):
    monkeypatch.setattr("app.core.cache._redis_client", lambda: None)
    with q.scope(2), pytest.raises(q.ThesisInferenceQuotaError, match="store_unavailable"):
        q.reserve_request(URL, PAYLOAD)
    q.reserve_request(URL, PAYLOAD)


def test_http_retries_and_failures_consume_attempts_other_routes_unaffected(store):
    calls = []
    async def call(scoped):
        def handler(req):
            calls.append(req)
            return httpx.Response(500, json={"error": "failed"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            p = create_llm_provider(Settings(_env_file=None, opencode_go_api_key="test", llm_max_retries=1), client=client)
            if scoped:
                with q.scope(2):
                    return await p.complete(LLMRequest(messages=[Message("user", "test")], max_tokens=700, cache=False))
            return await p.complete(LLMRequest(messages=[Message("user", "chat unchanged")], max_tokens=800, cache=False))
    for _ in range(6):
        with pytest.raises(LLMError):
            asyncio.run(call(True))
    assert len(calls) == 10
    assert list(store.counts.values()) == [10, 10]
    with pytest.raises(LLMError):
        asyncio.run(call(False))
    assert len(calls) == 12
    assert list(store.counts.values()) == [10, 10]


def test_oversize_input_fails_before_reserving(store):
    with q.scope(2), pytest.raises(q.ThesisInferenceQuotaError, match="request_bytes_exceeded"):
        q.reserve_request(URL, {**PAYLOAD, "messages": [{"content": "x" * 65536}]})
    assert not store.counts


def test_global_atomic_cap_across_many_tenants_and_utc_reset(store):
    now = datetime(2026, 11, 3, 23, 59, tzinfo=UTC)
    def call(i):
        try:
            q._reserve(i % 16 + 1, now)
            return 1
        except q.ThesisInferenceQuotaError:
            return 0
    with ThreadPoolExecutor(max_workers=32) as pool:
        assert sum(pool.map(call, range(320))) == 30
    assert store.counts["cavaai:thesis-input-inference:global:day:20261103"] == 30
    assert max(v for k, v in store.counts.items() if ":global:" not in k) <= 10
    before = store.counts.copy()
    with pytest.raises(q.ThesisInferenceQuotaError):
        q._reserve(99, now)
    assert store.counts == before  # no tenant reservation when global is exhausted
    q._reserve(99, datetime(2026, 11, 4, tzinfo=UTC))
    assert store.counts["cavaai:thesis-input-inference:global:day:20261104"] == 1


def test_tenant_rejection_does_not_consume_global_and_flag_only_feature(store):
    now = datetime(2026, 11, 3, tzinfo=UTC)
    for _ in range(10):
        q._reserve(2, now)
    before = store.counts.copy()
    with pytest.raises(q.ThesisInferenceQuotaError):
        q._reserve(2, now)
    assert store.counts == before
    store.counts[q.ENABLED_KEY] = "0"
    before = store.counts.copy()
    with q.scope(3), pytest.raises(q.ThesisInferenceQuotaError, match="feature_disabled"):
        q.reserve_request(URL, PAYLOAD)
    q.reserve_request("https://other.example", {})
    assert store.counts == before
