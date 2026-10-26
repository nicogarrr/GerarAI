"""Guard duro por corrida: se aplica ANTES de la red y no se reinicia por instancia."""

import asyncio

import httpx
import pytest

from app.core.config import Settings
from app.llm import LLMRequest, Message, create_llm_provider
from app.llm.errors import LLMError
from app.llm.run_guard import (
    InMemoryCounterStore,
    LLMGuardAbort,
    LLMRunGuard,
    RedisCounterStore,
    activate,
    current_guard,
)

HOST = "opencode.test"
URL = f"https://{HOST}/zen/go/v1"
MODEL = "deepseek-v4.1-flash"


def _guard(store, **kw):
    base = dict(
        run_id="run-1",
        allowed_hosts=frozenset({HOST}),
        allowed_models=frozenset({MODEL}),
        max_posts=3,
        max_tokens_per_request=2000,
        max_total_output_tokens=4000,
        store=store,
    )
    base.update(kw)
    return LLMRunGuard(**base)


class _Net:
    def __init__(self, statuses=(200,)):
        self.calls = 0
        self.statuses = list(statuses)

    def handler(self, request):
        self.calls += 1
        status = self.statuses[min(self.calls - 1, len(self.statuses) - 1)]
        if status != 200:
            return httpx.Response(status, json={"error": "x"})
        return httpx.Response(
            200,
            json={
                "id": "r",
                "model": MODEL,
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )


def _call(net, *, max_tokens=1000, base_url=URL):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(net.handler)) as client:
            provider = create_llm_provider(
                Settings(
                    _env_file=None,
                    opencode_go_api_key="k",
                    opencode_go_base_url=base_url,
                    opencode_go_model=MODEL,
                ),
                client=client,
            )
            return await provider.complete(
                LLMRequest(
                    messages=[Message("user", "hola")], task="cheap_extraction", max_tokens=max_tokens
                )
            )

    return asyncio.run(scenario())


def test_inactive_guard_changes_nothing():
    net = _Net()
    assert current_guard() is None
    assert _call(net).text == "ok"
    assert net.calls == 1


def test_posts_cap_blocks_before_network_and_survives_new_provider_instances():
    net = _Net()
    store = InMemoryCounterStore()
    with activate(_guard(store, max_total_output_tokens=10**6)):
        for _ in range(3):
            _call(net, max_tokens=100)  # cada llamada crea otro proveedor
        with pytest.raises(LLMGuardAbort) as err:
            _call(net, max_tokens=100)
    assert err.value.reason == "run_budget_exhausted"
    assert net.calls == 3  # la 4.a no salio


def test_retries_count_as_posts():
    net = _Net(statuses=(500, 500, 500))
    store = InMemoryCounterStore()
    with activate(_guard(store, max_posts=2)):
        with pytest.raises(LLMError):
            _call(net, max_tokens=100)
    assert net.calls == 2  # el 3.er intento del adaptador se aborta antes de red
    assert store.state["run-1"][0] == 2


def test_output_token_budget_is_reserved_by_requested_max_tokens():
    net = _Net()
    store = InMemoryCounterStore()
    with activate(_guard(store, max_total_output_tokens=2500)):
        _call(net, max_tokens=1500)
        with pytest.raises(LLMGuardAbort) as err:
            _call(net, max_tokens=1500)
    assert err.value.reason == "run_budget_exhausted"
    assert net.calls == 1


def test_per_request_cap_destination_and_model():
    net = _Net()
    store = InMemoryCounterStore()
    with activate(_guard(store)):
        with pytest.raises(LLMGuardAbort) as e1:
            _call(net, max_tokens=2001)
        with pytest.raises(LLMGuardAbort) as e2:
            _call(net, base_url="https://evil.test/zen/go/v1")
        with pytest.raises(LLMGuardAbort) as e3:
            _call(net, base_url="http://opencode.test/zen/go/v1")
    assert e1.value.reason == "max_tokens_per_request_exceeded"
    assert e2.value.reason == "destination_not_allowed"
    assert e3.value.reason == "destination_not_allowed"
    assert net.calls == 0
    assert "run-1" not in store.state


def test_model_not_allowed():
    net = _Net()
    with activate(_guard(InMemoryCounterStore(), allowed_models=frozenset({"other"}))):
        with pytest.raises(LLMGuardAbort) as err:
            _call(net)
    assert err.value.reason == "model_not_allowed"
    assert net.calls == 0


def test_guard_scope_propagates_to_tasks_and_resets():
    net = _Net()
    store = InMemoryCounterStore()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(net.handler)) as client:
            provider = create_llm_provider(
                Settings(
                    _env_file=None,
                    opencode_go_api_key="k",
                    opencode_go_base_url=URL,
                    opencode_go_model=MODEL,
                ),
                client=client,
            )
            req = LLMRequest(messages=[Message("user", "x")], task="cheap_extraction", max_tokens=100)
            with activate(_guard(store, max_posts=2)):
                await asyncio.gather(
                    asyncio.create_task(provider.complete(req)),
                    asyncio.create_task(provider.complete(req)),
                )
                with pytest.raises(LLMGuardAbort):
                    await asyncio.create_task(provider.complete(req))
            assert current_guard() is None

    asyncio.run(scenario())
    assert net.calls == 2


class _FailingRedis:
    def eval(self, *a, **k):
        raise ConnectionError("down")


def test_store_failure_fails_closed():
    net = _Net()
    with activate(_guard(RedisCounterStore(_FailingRedis()))):
        with pytest.raises(LLMGuardAbort) as err:
            _call(net)
    assert err.value.reason == "store_unavailable"
    assert net.calls == 0


def test_redis_store_passes_atomic_script_args_and_denies_on_zero():
    class Fake:
        def __init__(self, result):
            self.result = result
            self.args = None

        def eval(self, *args):
            self.args = args
            return self.result

    ok = Fake(1)
    assert RedisCounterStore(ok).reserve("r", posts=1, tokens=100, max_posts=8, max_tokens=22400)
    assert ok.args[2:] == ("llmguard:r", 1, 100, 8, 22400, 7 * 24 * 3600)
    assert not RedisCounterStore(Fake(0)).reserve("r", posts=1, tokens=100, max_posts=8, max_tokens=22400)


# --- cableado: Jev, guard_required, hilos puente, TTL fijo ---

def test_guard_required_blocks_go_provider_without_active_guard():
    net = _Net()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(net.handler)) as client:
            provider = create_llm_provider(
                Settings(
                    _env_file=None,
                    opencode_go_api_key="k",
                    opencode_go_base_url=URL,
                    opencode_go_model=MODEL,
                    llm_run_guard_required=True,
                ),
                client=client,
            )
            return await provider.complete(
                LLMRequest(messages=[Message("user", "x")], task="cheap_extraction", max_tokens=100)
            )

    with pytest.raises(LLMGuardAbort) as err:
        asyncio.run(scenario())
    assert err.value.reason == "guard_required_but_inactive"
    assert net.calls == 0


def test_jev_post_is_blocked_by_active_guard_and_when_required_without_guard():
    from app.llm.jev import JevDecisionClient

    net = _Net()

    async def call(required):
        async with httpx.AsyncClient(transport=httpx.MockTransport(net.handler)) as client:
            jev = JevDecisionClient("k", client=client)
            jev.guard_required = required
            return await jev.systemone({"message": "x"}, {"q": {"type": "choice"}})

    with activate(_guard(InMemoryCounterStore())):
        with pytest.raises(LLMGuardAbort) as e1:
            asyncio.run(call(False))
    with pytest.raises(LLMGuardAbort) as e2:
        asyncio.run(call(True))
    assert e1.value.reason == "destination_not_allowed"
    assert e2.value.reason == "guard_required_but_inactive"
    assert net.calls == 0


def test_guard_reaches_bridge_thread_via_run_from_any_context():
    from app.services.async_bridge import run_from_any_context

    net = _Net()
    store = InMemoryCounterStore()

    async def inner():
        # Con loop activo en este hilo, run_from_any_context usa el hilo puente.
        async def probe():
            return current_guard() is not None

        return run_from_any_context(probe())

    with activate(_guard(store)):
        assert asyncio.run(inner()) is True
    assert net.calls == 0


def test_redis_script_sets_ttl_once_not_sliding():
    from app.llm import run_guard

    assert "TTL" in run_guard._RESERVE_LUA
    assert run_guard._RESERVE_LUA.count("EXPIRE") == 1
    assert "< 0" in run_guard._RESERVE_LUA


def _jev_call(net, store, *, max_posts, retries=2):
    from app.llm.jev import JevDecisionClient

    async def call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(net.handler)) as client:
            jev = JevDecisionClient(
                "k", base_url=f"https://{HOST}", client=client, max_retries=retries
            )
            return await jev.systemone({"message": "x"}, {"q": {"type": "choice"}})

    with activate(_guard(store, max_posts=max_posts)):
        return asyncio.run(call())


def test_jev_allowlisted_host_consumes_one_post_per_attempt_and_respects_cap():
    store = InMemoryCounterStore()
    net = _Net()
    _jev_call(net, store, max_posts=3)
    assert net.calls == 1
    assert store.state["run-1"] == (1, 0)  # tokens de salida: 0, no se inventa coste


def test_jev_retries_count_against_post_cap_and_deny_without_network():
    store = InMemoryCounterStore()
    net = _Net(statuses=(500,))
    with pytest.raises(LLMGuardAbort) as err:
        _jev_call(net, store, max_posts=2, retries=5)
    assert err.value.reason == "run_budget_exhausted"
    assert net.calls == 2  # el 3er intento se corta antes de la red
    assert store.state["run-1"] == (2, 0)


def test_jev_allowlisted_cap_exhausted_from_other_providers_blocks_jev():
    store = InMemoryCounterStore()
    store.state["run-1"] = (3, 0)
    net = _Net()
    with pytest.raises(LLMGuardAbort) as err:
        _jev_call(net, store, max_posts=3)
    assert err.value.reason == "run_budget_exhausted"
    assert net.calls == 0


def test_redis_strict_mode_args_and_error_codes():
    class Fake:
        def __init__(self, result):
            self.result = result
            self.calls = []

        def eval(self, *args):
            self.calls.append(args)
            return self.result

    f = Fake(1)
    st = RedisCounterStore(f)
    assert st.reserve("r", posts=1, tokens=0, max_posts=8, max_tokens=22400, deadline_ts=2000.5)
    assert f.calls[0][-1] == 2000500  # deadline absoluto en ms, evaluado con TIME de Redis
    for code, reason in ((-2, "run_deadline_exceeded"), (-1, "counter_missing")):
        with pytest.raises(LLMGuardAbort) as e:
            RedisCounterStore(Fake(code)).reserve("r", posts=1, tokens=0, max_posts=8, max_tokens=1, deadline_ts=1.0)
        assert e.value.reason == reason
    st.init("r", deadline_ts=10.0)
    assert f.calls[-1][2:] == ("llmguard:r", 10000)
