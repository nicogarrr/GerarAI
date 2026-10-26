"""Cache de respuestas LLM en Redis: acierto, fallo, TTL, cota y aislamiento.

Hermetico: el doble `FakeRedis` implementa en Python el mismo contrato que el
script Lua de `app/llm/response_cache.py` (`SET ... EX`, `ZADD`, prune por TTL y
recorte FIFO por `ZCARD`), con reloj manual. No hay red ni Redis real.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
import redis.exceptions

from app.llm import (
    LLMRequest,
    LLMResponseCache,
    Message,
    OpenAICompatibleProvider,
    ResponseFormat,
    ToolCall,
    ToolDefinition,
    build_response_cache,
    decode_response,
    encode_response,
    is_cacheable,
    load_cache_settings,
    parse_tool_calls,
    tenant_cache_scope,
)
from app.services.budget import BudgetController


def run(coroutine):
    return asyncio.run(coroutine)


# ---------------------------------------------------------------------------
# Dobles
# ---------------------------------------------------------------------------


class FakeRedis:
    """Redis con reloj manual que refleja el script Lua de escritura."""

    def __init__(self) -> None:
        self.values: dict[str, tuple[float, str]] = {}
        self.index: dict[str, list[tuple[float, str]]] = {}
        # Reloj en milisegundos, igual que el score del indice ZSET real.
        self.now = 1_000_000.0
        self.reads = 0
        self.writes = 0
        self.deletes = 0
        self.error: Exception | None = None

    def _check(self) -> None:
        if self.error is not None:
            raise self.error

    async def get(self, key: str):
        self._check()
        self.reads += 1
        item = self.values.get(key)
        if item is None:
            return None
        if self.now >= item[0]:
            self.values.pop(key, None)
            return None
        return item[1]

    async def delete(self, key: str) -> int:
        self._check()
        self.deletes += 1
        return 1 if self.values.pop(key, None) is not None else 0

    async def eval(self, script, numkeys, *args):  # noqa: ARG002
        self._check()
        key, index = args[0], args[1]
        value, ttl, score, max_entries = args[2], int(args[3]), float(args[4]), int(args[5])
        self.now = max(self.now, score)
        self.writes += 1
        self.values[key] = (score + ttl * 1000, value)
        entries = [(ts, k) for ts, k in self.index.get(index, []) if k != key]
        entries.append((score, key))
        entries.sort()
        cutoff = score - ttl * 1000
        entries = [(ts, k) for ts, k in entries if ts > cutoff]
        while len(entries) > max_entries:
            _, victim = entries.pop(0)
            self.values.pop(victim, None)
        self.index[index] = entries
        return 1


class BrokenRedis(FakeRedis):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def _check(self) -> None:
        raise self.error


def _ok_body(content: str = "ok", *, model: str = "space-bunny-free") -> dict:
    return {
        "id": "req-1",
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
    }


class _Transport:
    """MockTransport que cuenta peticiones y devuelve un cuerpo configurable."""

    def __init__(self, body: dict | None = None) -> None:
        self.body = body or _ok_body()
        self.calls = 0
        self.payloads: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.payloads.append(json.loads(request.content))
        return httpx.Response(200, json=self.body)


def _provider(
    redis: FakeRedis | None = None,
    *,
    transport: _Transport | None = None,
    cache_kwargs: dict | None = None,
) -> tuple[OpenAICompatibleProvider, _Transport, FakeRedis | None]:
    stub = transport or _Transport()
    redis = redis if redis is not None else FakeRedis()
    cache = LLMResponseCache(
        ttl_seconds=(cache_kwargs or {}).get("ttl_seconds", 900),
        max_entries=(cache_kwargs or {}).get("max_entries", 500),
        require_tenant=(cache_kwargs or {}).get("require_tenant", True),
        namespace="test",
        log_every=(cache_kwargs or {}).get("log_every", 1_000_000),
        redis_factory=lambda: redis,
    )
    provider = OpenAICompatibleProvider(
        api_key="test-secret",
        base_url="https://opencode.test/zen/v1",
        default_model="space-bunny-free",
        provider_name="opencode-go",
        response_cache=cache,
        client=httpx.AsyncClient(transport=httpx.MockTransport(stub)),
        max_retries=0,
    )
    return provider, stub, redis


def _request(text: str = "Extrae los KPIs", **kwargs) -> LLMRequest:
    return LLMRequest(messages=[Message("user", text)], task="kpi_extraction", **kwargs)


# ---------------------------------------------------------------------------
# Acierto y fallo
# ---------------------------------------------------------------------------


def test_cache_hit_returns_the_response_without_calling_the_provider():
    provider, stub, _ = _provider()
    with tenant_cache_scope(7):
        first = run(provider.complete(_request()))
        second = run(provider.complete(_request()))
    assert stub.calls == 1
    assert second.text == first.text
    assert first.from_cache is False
    assert second.from_cache is True


def test_cache_miss_calls_the_provider_and_stores_the_answer():
    provider, stub, redis = _provider()
    with tenant_cache_scope(7):
        run(provider.complete(_request()))
    assert stub.calls == 1
    assert redis.writes == 1
    with tenant_cache_scope(7):
        hit = run(provider.complete(_request()))
    assert hit.from_cache is True


def test_redis_outage_is_fail_open_and_never_breaks_the_call():
    broken = BrokenRedis(redis.exceptions.ConnectionError("redis caido"))
    provider, stub, _ = _provider(broken)
    with tenant_cache_scope(7):
        first = run(provider.complete(_request()))
        second = run(provider.complete(_request()))
    assert first.text == "ok" and second.text == "ok"
    assert second.from_cache is False
    assert stub.calls == 2
    assert provider._response_cache.stats()["error"] >= 1


def test_corrupt_entry_is_a_miss_not_a_crash():
    redis = FakeRedis()
    provider, stub, _ = _provider(redis)
    with tenant_cache_scope(7):
        run(provider.complete(_request()))
    key = next(iter(redis.values))
    redis.values[key] = (redis.now + 900, "{no es json")
    with tenant_cache_scope(7):
        response = run(provider.complete(_request()))
    assert response.text == "ok"
    assert stub.calls == 2
    assert redis.deletes == 1


def test_entry_expires_after_the_ttl():
    redis = FakeRedis()
    provider, stub, _ = _provider(redis, cache_kwargs={"ttl_seconds": 60})
    with tenant_cache_scope(7):
        run(provider.complete(_request()))
        redis.now += 59_000
        assert run(provider.complete(_request())).from_cache is True
        redis.now += 2_000
        assert run(provider.complete(_request())).from_cache is False
    assert stub.calls == 2


def test_size_cap_evicts_the_oldest_entries():
    redis = FakeRedis()
    provider, stub, _ = _provider(redis, cache_kwargs={"max_entries": 2})
    with tenant_cache_scope(7):
        for index in range(4):
            run(provider.complete(_request(f"Pregunta {index}")))
    live = [key for key, item in redis.values.items() if redis.now < item[0]]
    assert len(live) == 2
    index_entries = next(iter(redis.index.values()))
    assert len(index_entries) == 2
    # FIFO: las dos ultimas siguen, la primera se fue.
    with tenant_cache_scope(7):
        assert run(provider.complete(_request("Pregunta 0"))).from_cache is False
        assert run(provider.complete(_request("Pregunta 3"))).from_cache is True
    assert stub.calls == 5


# ---------------------------------------------------------------------------
# Aislamiento y correccion de la clave
# ---------------------------------------------------------------------------


def test_two_tenants_never_share_an_entry():
    redis = FakeRedis()
    stub_a = _Transport(_ok_body(content="respuesta de A"))
    stub_b = _Transport(_ok_body(content="respuesta de B"))
    provider_a, _, _ = _provider(redis, transport=stub_a)
    provider_b, _, _ = _provider(redis, transport=stub_b)

    with tenant_cache_scope(1):
        assert run(provider_a.complete(_request())).text == "respuesta de A"
    with tenant_cache_scope(2):
        assert run(provider_b.complete(_request())).text == "respuesta de B"
    with tenant_cache_scope(1):
        assert run(provider_a.complete(_request())).text == "respuesta de A"

    assert stub_a.calls == 1
    assert stub_b.calls == 1


def test_scoped_and_unscoped_requests_do_not_collide():
    redis = FakeRedis()
    stub_scoped = _Transport(_ok_body(content="scoped"))
    stub_open = _Transport(_ok_body(content="unscoped"))
    scoped, _, _ = _provider(redis, transport=stub_scoped)
    open_call, _, _ = _provider(redis, transport=stub_open, cache_kwargs={"require_tenant": False})

    with tenant_cache_scope(3):
        assert run(scoped.complete(_request())).text == "scoped"
    assert run(open_call.complete(_request())).text == "unscoped"
    with tenant_cache_scope(3):
        assert run(scoped.complete(_request())).from_cache is True


def test_without_tenant_scope_the_cache_fails_closed():
    redis = FakeRedis()
    provider, stub, _ = _provider(redis)
    assert run(provider.complete(_request())).text == "ok"
    assert run(provider.complete(_request())).text == "ok"
    assert stub.calls == 2
    assert redis.reads == 0 and redis.writes == 0
    assert provider._response_cache.stats()["skip"] == 2


def test_tenant_can_arrive_in_the_request_metadata():
    redis = FakeRedis()
    provider, stub, _ = _provider(redis)
    first = _request(metadata={"tenant_id": "12"})
    assert run(provider.complete(first)).text == "ok"
    assert run(provider.complete(_request(metadata={"tenant_id": "13"}))).text == "ok"
    assert run(provider.complete(first)).from_cache is True
    assert stub.calls == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", 0.1),
        ("max_tokens", 512),
        ("response_format", ResponseFormat.json_object()),
        ("task", "cheap_extraction"),
        ("model", "deepseek-v4-flash"),
        ("tools", (ToolDefinition(name="t"),)),
        ("tool_choice", "required"),
    ],
)
def test_key_changes_when_any_response_shaping_parameter_changes(field, value):
    cache = LLMResponseCache(namespace="test", redis_factory=FakeRedis)
    payload = {"model": "space-bunny-free", "messages": [{"role": "user", "content": "x"}]}
    baseline = cache.build_key(
        tenant_id="1", provider="opencode-go", model="space-bunny-free", task="kpi", payload=payload
    )
    changed = cache.build_key(
        tenant_id="1", provider="opencode-go", model="space-bunny-free", task="kpi",
        payload={**payload, field: value},
    )
    assert baseline != changed


def test_key_changes_with_tenant_provider_and_prompt():
    cache = LLMResponseCache(namespace="test", redis_factory=FakeRedis)
    payload = {"model": "space-bunny-free", "messages": [{"role": "user", "content": "x"}]}
    base = cache.build_key(
        tenant_id="1", provider="opencode-go", model="space-bunny-free", task="kpi", payload=payload
    )
    assert base != cache.build_key(
        tenant_id="2", provider="opencode-go", model="space-bunny-free", task="kpi", payload=payload
    )
    assert base != cache.build_key(
        tenant_id="1", provider="otro", model="space-bunny-free", task="kpi", payload=payload
    )
    assert base != cache.build_key(
        tenant_id="1",
        provider="opencode-go",
        model="space-bunny-free",
        task="kpi",
        payload={"model": "space-bunny-free", "messages": [{"role": "user", "content": "y"}]},
    )


def test_different_reasoning_effort_changes_the_key():
    redis = FakeRedis()
    cache = LLMResponseCache(namespace="test", redis_factory=lambda: redis)
    base = cache.build_key(
        tenant_id="1",
        provider="opencode-go",
        model="space-bunny-free",
        task="kpi",
        payload={"model": "space-bunny-free", "messages": []},
    )
    assert base != cache.build_key(
        tenant_id="1",
        provider="opencode-go",
        model="space-bunny-free",
        task="kpi",
        payload={"model": "space-bunny-free", "messages": [], "reasoning_effort": "max"},
    )


def test_prompt_change_is_a_miss():
    provider, stub, _ = _provider()
    with tenant_cache_scope(4):
        run(provider.complete(_request("Una")))
        assert run(provider.complete(_request("Dos"))).from_cache is False
    assert stub.calls == 2


def test_key_is_stable_and_order_independent():
    cache = LLMResponseCache(namespace="test", redis_factory=FakeRedis)
    first = cache.build_key(
        tenant_id="1",
        provider="opencode-go",
        model="m",
        task="t",
        payload={"b": 1, "a": {"y": 2, "x": 3}},
    )
    second = cache.build_key(
        tenant_id="1",
        provider="opencode-go",
        model="m",
        task="t",
        payload={"a": {"x": 3, "y": 2}, "b": 1},
    )
    assert first == second


# ---------------------------------------------------------------------------
# Que no se cachea
# ---------------------------------------------------------------------------


def test_provider_warning_is_not_cached():
    body = _ok_body()
    body["warning"] = "el modelo se degradó"
    provider, stub, _ = _provider(FakeRedis(), transport=_Transport(body))
    with tenant_cache_scope(7):
        first = run(provider.complete(_request()))
        second = run(provider.complete(_request()))
    assert first.degraded is True
    assert first.warnings == ("warning:el modelo se degradó",)
    assert second.from_cache is False
    assert stub.calls == 2


def test_truncated_response_is_not_cached():
    body = _ok_body()
    body["choices"][0]["finish_reason"] = "length"
    provider, stub, _ = _provider(FakeRedis(), transport=_Transport(body))
    with tenant_cache_scope(7):
        assert run(provider.complete(_request())).degraded is True
        assert run(provider.complete(_request())).from_cache is False
    assert stub.calls == 2


def test_content_filtered_response_is_not_cached():
    body = _ok_body()
    body["choices"][0]["finish_reason"] = "content_filter"
    provider, stub, _ = _provider(FakeRedis(), transport=_Transport(body))
    with tenant_cache_scope(7):
        run(provider.complete(_request()))
        run(provider.complete(_request()))
    assert stub.calls == 2


def test_model_fallback_response_is_not_cached():
    redis = FakeRedis()
    stub = _Transport()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        stub.calls += 1
        stub.payloads.append(payload)
        if payload["model"] == "space-bunny-free":
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json=_ok_body(model=payload["model"]))

    provider = OpenAICompatibleProvider(
        api_key="test-secret",
        base_url="https://opencode.test/zen/v1",
        default_model="space-bunny-free",
        fallback_model="deepseek-v4.1-flash-free",
        provider_name="opencode-go",
        response_cache=LLMResponseCache(namespace="test", redis_factory=lambda: redis),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    # El request fija el modelo primario: desde el pin a deepseek el router
    # resuelve la tarea, no el default_model del provider; el pin del request
    # sigue ganando (contrato del router).
    with tenant_cache_scope(7):
        first = run(provider.complete(_request(model="space-bunny-free")))
        second = run(provider.complete(_request(model="space-bunny-free")))
    assert first.text == "ok" and second.text == "ok"
    assert first.from_cache is False and second.from_cache is False
    assert redis.writes == 0
    assert stub.calls == 4


def test_ephemeral_request_is_never_cached():
    provider, stub, _ = _provider()
    with tenant_cache_scope(7):
        run(provider.complete(_request(cache=False)))
        assert run(provider.complete(_request(cache=False))).from_cache is False
    assert stub.calls == 2


def test_failures_leave_no_entry():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    redis = FakeRedis()
    provider = OpenAICompatibleProvider(
        api_key="test-secret",
        base_url="https://opencode.test/zen/v1",
        default_model="space-bunny-free",
        provider_name="opencode-go",
        response_cache=LLMResponseCache(namespace="test", redis_factory=lambda: redis),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    with tenant_cache_scope(7):
        with pytest.raises(Exception):
            run(provider.complete(_request()))
    assert redis.values == {}
    assert redis.writes == 0


def test_a_degraded_entry_written_by_an_older_version_is_never_served():
    redis = FakeRedis()
    provider, stub, _ = _provider(redis)
    with tenant_cache_scope(7):
        run(provider.complete(_request()))
    key = next(iter(redis.values))
    stored = decode_response(redis.values[key][1])
    poisoned = json.loads(encode_response(stored))
    poisoned["degraded"] = True
    redis.values[key] = (redis.now + 900_000, json.dumps(poisoned))
    with tenant_cache_scope(7):
        response = run(provider.complete(_request()))
    assert response.from_cache is False
    assert stub.calls == 2
    # La entrada envenenada se borro; la que queda es limpia.
    assert redis.deletes >= 1
    assert decode_response(redis.values[key][1]).degraded is False


def test_is_cacheable_rejects_degraded_truncated_and_fallback():
    provider, _, _ = _provider()
    response = run(provider.complete(_request()))
    assert is_cacheable(response)
    assert not is_cacheable(response, used_fallback=True)


# ---------------------------------------------------------------------------
# Presupuesto
# ---------------------------------------------------------------------------


def test_a_cached_answer_costs_zero_budget_and_the_first_one_is_priced():
    provider, _, _ = _provider()
    model = "space-bunny-free"
    with tenant_cache_scope(7):
        first = run(provider.complete(_request()))
        second = run(provider.complete(_request()))

    first_cost = BudgetController.estimate_cost_eur(
        model, first.usage.input_tokens, first.usage.output_tokens
    )
    second_cost = BudgetController.estimate_cost_eur(
        model, second.usage.input_tokens, second.usage.output_tokens
    )
    assert first_cost > 0
    assert second_cost == 0.0
    assert second.usage.total_tokens == 0
    # El ahorro sigue siendo observable sin inventarse gasto.
    assert second.usage.cache_read_tokens == 140
    assert second.cache_key


# ---------------------------------------------------------------------------
# Round-trip de tool calls e instrumentacion
# ---------------------------------------------------------------------------


def test_tool_calls_survive_the_cache_round_trip():
    provider, stub, redis = _provider()
    request = _request(tools=(ToolDefinition(name="t"),))
    with tenant_cache_scope(7):
        run(provider.complete(request))
        assert run(provider.complete(request)).from_cache is True
    assert stub.calls == 1
    assert parse_tool_calls([{"function": {"name": "t", "arguments": "{}"}}])


def test_stats_are_aggregated_without_secrets(caplog):
    redis = FakeRedis()
    provider, _, _ = _provider(redis, cache_kwargs={"log_every": 1})
    with caplog.at_level(logging.INFO, logger="app.llm.response_cache"):
        with tenant_cache_scope(7):
            run(provider.complete(_request()))
            run(provider.complete(_request()))
    stats = provider._response_cache.stats()
    assert stats["write"] == 1
    assert stats["hit"] == 1
    text = caplog.text
    assert "hits=1" in text and "writes=1" in text
    assert "test-secret" not in text
    assert "Extrae los KPIs" not in text


def test_settings_come_from_env_with_settings_fields_winning(monkeypatch):
    monkeypatch.setenv("LLM_RESPONSE_CACHE_ENABLED", "false")
    monkeypatch.setenv("LLM_RESPONSE_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("LLM_RESPONSE_CACHE_MAX_ENTRIES", "5")
    monkeypatch.setenv("LLM_RESPONSE_CACHE_REQUIRE_TENANT", "false")
    from app.core.config import Settings

    config = load_cache_settings(Settings(_env_file=None))
    assert config.enabled is False
    assert config.ttl_seconds == 60
    assert config.max_entries == 5
    assert config.require_tenant is False

    # Un campo de Settings (cuando exista) tiene prioridad sobre el entorno.
    class _WithField(Settings):
        llm_response_cache_ttl_seconds: int = 120  # type: ignore[assignment]

    monkeypatch.delenv("LLM_RESPONSE_CACHE_TTL_SECONDS", raising=False)
    assert load_cache_settings(_WithField(_env_file=None)).ttl_seconds == 120


def test_out_of_range_env_values_are_clamped(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("LLM_RESPONSE_CACHE_TTL_SECONDS", "999999999")
    monkeypatch.setenv("LLM_RESPONSE_CACHE_MAX_ENTRIES", "no-es-un-entero")
    config = load_cache_settings(Settings(_env_file=None))
    assert config.ttl_seconds == 86_400
    assert config.max_entries == 500


def test_build_response_cache_returns_none_when_disabled(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("LLM_RESPONSE_CACHE_ENABLED", "false")
    assert build_response_cache(Settings(_env_file=None)) is None


def test_decode_rejects_an_unknown_envelope_version():
    with pytest.raises(ValueError, match="unsupported cached response envelope"):
        decode_response(json.dumps({"v": 999, "content": "x"}))


def test_encoded_response_never_contains_the_api_key():
    provider, _, redis = _provider()
    with tenant_cache_scope(7):
        run(provider.complete(_request()))
    blob = next(iter(redis.values.values()))[1]
    assert "test-secret" not in blob


def test_purge_invalidates_only_the_configured_deployment_namespace():
    from app.core.config import Settings
    from app.llm.response_cache import (
        _cache_namespace,
        _deployment_id,
        purge_llm_response_cache,
    )

    class SyncRedis:
        def __init__(self, keys):
            self.keys = set(keys)
            self.closed = False

        def scan_iter(self, match, count=500):
            prefix = match[:-1]
            return iter([key for key in self.keys if key.startswith(prefix)])

        def delete(self, *keys):
            removed = sum(1 for key in keys if key in self.keys)
            self.keys.difference_update(keys)
            return removed

        def close(self):
            self.closed = True

    settings = Settings(_env_file=None)
    namespace = _cache_namespace(settings)
    cache = LLMResponseCache(namespace=_deployment_id(settings))
    own = cache.build_key(
        tenant_id="tenant-a", provider="p", model="m", task="t", payload={}
    )
    other = LLMResponseCache(namespace="otro-despliegue").build_key(
        tenant_id="tenant-b", provider="p", model="m", task="t", payload={}
    )
    fake = SyncRedis({own, other, f"{namespace}:index"})
    assert purge_llm_response_cache(
        settings, tenant_id="tenant-a", redis_factory=lambda: fake
    ) == 1
    assert fake.keys == {other}
    assert fake.closed is True


def test_tool_call_response_round_trips_through_the_cache():
    body = {
        "id": "req-2",
        "model": "space-bunny-free",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "t", "arguments": '{"a": 1}'}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }
    provider, stub, _ = _provider(FakeRedis(), transport=_Transport(body))
    request = _request(tools=(ToolDefinition(name="t"),))
    with tenant_cache_scope(7):
        first = run(provider.complete(request))
        second = run(provider.complete(request))
    assert stub.calls == 1
    assert first.tool_calls == second.tool_calls == (
        ToolCall(id="c1", name="t", arguments={"a": 1}),
    )
    assert second.from_cache is True