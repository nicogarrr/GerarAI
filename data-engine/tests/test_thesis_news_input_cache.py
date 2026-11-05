"""Hermetic provider doubles: cache reuse must never spend or mix tenants."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_thesis_news_narrative import ITEM, NOW, Provider, output

from app.services import thesis_news_cache as cache
from app.services import thesis_news_narrative as svc


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "1")
    data, writes, records = {}, [], []

    class Redis:
        def get(self, key):
            return data.get(key)

        def set(self, key, value, *, ex):
            data[key] = value
            writes.append((key, ex))

    class Budget:
        def can_spend(self, db, amount):
            return True

        def record(self, *args, **kwargs):
            records.append(args)

    monkeypatch.setattr(cache.cache, "_redis_client", lambda: Redis())
    monkeypatch.setattr(svc, "BudgetController", Budget)
    db = SimpleNamespace(info={"tenant_id": 2, "language": "es"}, flush=lambda: None)
    return SimpleNamespace(db=db, company=SimpleNamespace(ticker="META"),
                           data=data, writes=writes, records=records)


def call(state, provider, items=None):
    return svc.maybe_news_narrative_sections(
        state.db, state.company, items or [ITEM], provider=provider, now=NOW,
    )


def test_identical_input_zero_extra_calls_and_no_fake_accounting(state):
    provider = Provider()
    first = call(state, provider)
    assert call(state, provider) == first
    assert provider.calls == 1
    assert len(state.records) == 1
    assert len(state.writes) == 1
    assert state.writes[0][1] == cache.TTL_SECONDS


@pytest.mark.parametrize("change", ["tenant", "language", "evidence", "ticker", "model", "prompt", "effort", "endpoint", "credential"])
def test_changed_scope_or_input_misses(state, monkeypatch, change):
    provider = Provider()
    call(state, provider)
    items = [dict(ITEM)]
    if change == "tenant":
        state.db.info["tenant_id"] = 5
    elif change == "language":
        monkeypatch.setattr(cache, "current_language", lambda: "en")
    elif change == "evidence":
        items[0]["source_headline"] += " comercial"
    elif change == "ticker":
        state.company.ticker = "TSLA"
    elif change == "model":
        provider.model_router = SimpleNamespace(resolve=lambda request: "deepseek-v4.1-flash-free")
    elif change == "endpoint":
        provider._base_url = "https://example.org/v1"
    elif change == "credential":
        provider._api_key = "test-only-credential"
    else:
        original = svc.build_request
        def build(*args):
            request = original(*args)
            if change == "effort":
                return replace(request, reasoning_effort="max")
            return replace(request, messages=[replace(request.messages[0], content="Changed prompt"), request.messages[1]])
        monkeypatch.setattr(svc, "build_request", build)
    call(state, provider, items)
    assert provider.calls == 2


@pytest.mark.parametrize("tenant", [None, 0, "2", True])
def test_unscoped_never_cached(state, tenant):
    state.db.info["tenant_id"] = tenant
    provider = Provider()
    call(state, provider)
    call(state, provider)
    assert provider.calls == 2
    assert not state.writes


def test_rejected_cached_payload_revalidated(state):
    provider = Provider()
    call(state, provider)
    import json
    for key in state.data:
        state.data[key] = json.dumps(output("La valoración es de 123 millones y podría crecer mucho."))
    call(state, provider)
    assert provider.calls == 2


def test_invalid_provider_output_not_cached(state):
    provider = Provider(text="{}")
    call(state, provider)
    call(state, provider)
    assert provider.calls == 2
    assert not state.writes


def test_fallback_model_not_pinned_under_primary(state):
    provider = Provider(model="deepseek-v4.1-flash-free")
    call(state, provider)
    call(state, provider)
    assert provider.calls == 2
    assert not state.writes


def test_redis_down_preserves_valid_generation(state, monkeypatch):
    def down():
        raise ConnectionError("test")
    monkeypatch.setattr(cache.cache, "_redis_client", down)
    provider = Provider()
    first = call(state, provider)
    assert call(state, provider) == first
    assert provider.calls == 2
    assert len(state.records) == 2


def test_cache_get_and_set_failures_do_not_change_sections(state, monkeypatch):
    class BrokenRedis:
        def get(self, key):
            raise TimeoutError("test")
        def set(self, *args, **kwargs):
            raise TimeoutError("test")
    monkeypatch.setattr(cache.cache, "_redis_client", lambda: BrokenRedis())
    provider = Provider()
    first = call(state, provider)
    assert first[0]["parrafos"][0] == output()["cambio"]["texto"]
    assert call(state, provider) == first
    assert provider.calls == 2


def test_disabled_flag_does_not_consult_cache(state, monkeypatch):
    provider = Provider()
    call(state, provider)
    monkeypatch.setenv("THESIS_NARRATIVE_LLM_ENABLED", "0")
    assert call(state, provider) != call_expected_llm(state)
    assert provider.calls == 1


def call_expected_llm(state):
    return svc.validate_output(output(), svc.news_context([ITEM], NOW))


@pytest.mark.parametrize("field,value", [("degraded", True), ("warnings", ["test"]), ("finish_reason", "length")])
def test_degraded_or_truncated_output_not_cached(state, field, value):
    class Degraded(Provider):
        async def complete(self, request):
            response = await super().complete(request)
            setattr(response, field, value)
            return response
    provider = Degraded()
    call(state, provider)
    call(state, provider)
    assert provider.calls == 2
    assert not state.writes


def test_explicit_no_cache_not_reused(state, monkeypatch):
    original = svc.build_request
    monkeypatch.setattr(svc, "build_request", lambda *args: replace(original(*args), cache=False))
    provider = Provider()
    call(state, provider)
    call(state, provider)
    assert provider.calls == 2
    assert not state.writes


def test_ttl_expiry_forces_real_call(state):
    provider = Provider()
    call(state, provider)
    state.data.clear()  # Redis expires the key after the fixed TTL.
    call(state, provider)
    assert provider.calls == 2
    assert len(state.records) == 2
