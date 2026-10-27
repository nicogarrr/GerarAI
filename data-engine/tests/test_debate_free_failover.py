"""Hermetic quota failures: no network, no paid models, no retries of 429."""
import asyncio
import json
import time

import httpx
import pytest

from app.core.config import Settings
from app.llm import base
from app.llm.chat_provider import create_chat_llm_provider
from app.llm.contracts import LLMRequest, Message
from app.llm.free_interactive import FreeLLMUnavailable, create_free_interactive_provider
from app.services.thesis_debate_service import debate_thesis


@pytest.fixture(autouse=True)
def clean_breaker():
    base._free_tier_breaker.clear()
    base._free_tier_breaker_status.clear()
    base._interactive_quota_breaker.clear()
    yield
    base._free_tier_breaker.clear()
    base._free_tier_breaker_status.clear()
    base._interactive_quota_breaker.clear()


def settings(**kw):
    # Este fichero fija la ruta free/legacy: la suscripcion Go se apaga aqui.
    base = dict(
        _env_file=None, llm_enabled=True, llm_provider="opencode-go",
        opencode_go_api_key="test-key", chat_go_subscription_enabled=False,
        opencode_go_model="deepseek-v4.1-flash-free",
        opencode_go_fallback_model="space-bunny-free",
    )
    base.update(kw)
    return Settings(**base)


def envelope(text="Caso alcista: crecimiento con datos de la tesis."):
    return {"usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}


def test_debate_switches_on_first_429_and_shared_breaker_skips_it_next_time():
    calls = []
    def handle(req):
        model = json.loads(req.content)["model"]
        calls.append(model)
        if model.startswith("deepseek"):
            return httpx.Response(429, json={"error": {"type": "FreeTierLimitError"}})
        return httpx.Response(200, json=envelope())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = create_free_interactive_provider(settings(), client=client)
            request = LLMRequest([Message("user", "tesis")], task="red_team")
            assert (await provider.complete(request)).model == "space-bunny-free"
            assert (await provider.complete(request)).model == "space-bunny-free"
    asyncio.run(run())
    assert calls == ["deepseek-v4.1-flash-free", "space-bunny-free", "space-bunny-free"]


def test_all_exhausted_fail_fast_once_and_do_not_retry_bear_or_judge():
    calls = []
    def handle(req):
        calls.append(json.loads(req.content)["model"])
        return httpx.Response(429, json={"error": {"type": "FreeTierLimitError"}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = create_free_interactive_provider(settings(), client=client)
            started = time.monotonic()
            with pytest.raises(FreeLLMUnavailable, match="modelo configurado ha agotado su cuota"):
                await debate_thesis("EXEL", "tesis", provider=provider, strict_provider=True, use_jev=False)
            assert time.monotonic() - started < 1
            with pytest.raises(FreeLLMUnavailable, match="modelo configurado ha agotado su cuota"):
                await provider.complete(LLMRequest([Message("user", "otra")], task="red_team"))
    asyncio.run(run())
    assert calls == ["deepseek-v4.1-flash-free", "space-bunny-free"]


def test_chat_and_debate_share_per_model_breaker():
    calls = []
    def handle(req):
        model = json.loads(req.content)["model"]
        calls.append(model)
        return httpx.Response(429) if model.startswith("deepseek") else httpx.Response(200, json=envelope())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            chat = create_chat_llm_provider(settings(), client=client)
            assert (await chat.complete(LLMRequest([Message("user", "hola")], task="chat"))).model == "space-bunny-free"
            debate = create_free_interactive_provider(settings(), client=client)
            await debate.complete(LLMRequest([Message("user", "tesis")], task="red_team"))
    asyncio.run(run())
    assert calls == ["deepseek-v4.1-flash-free", "space-bunny-free", "space-bunny-free"]


def test_paid_environment_cannot_reach_debate_transport():
    # Con modelos no aprobados no hay debate: ni el modelo de pago ni un free
    # de respaldo silencioso (antes caia a deepseek-v4.1-flash-free).
    calls = []
    def handle(req):
        calls.append(json.loads(req.content)["model"])
        return httpx.Response(200, json=envelope())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            create_free_interactive_provider(settings(
                opencode_go_model="paid", opencode_go_fallback_model="also-paid",
                llm_model_overrides={"deepseek-v4.1-flash-free": "paid"}), client=client)
    with pytest.raises(FreeLLMUnavailable):
        asyncio.run(run())
    assert calls == []


def test_429_breaker_expiry_reprobes(monkeypatch):
    from app.llm.adapters import OpenAICompatibleProvider
    from app.llm.errors import ProviderHTTPError
    calls = []
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: (calls.append(1), httpx.Response(429))[1])) as client:
            p = OpenAICompatibleProvider(api_key="k", base_url="https://test.invalid", default_model="m",
                                         provider_name="opencode-go", client=client, max_retries=2)
            p.interactive_quota_breaker = True
            for _ in range(2):
                with pytest.raises(ProviderHTTPError) as exc:
                    await p._post_json("https://test.invalid", headers={}, payload={"model": "m"})
                assert exc.value.status_code == 429
            assert len(calls) == 1
            base._interactive_quota_breaker[("opencode-go", "m")] = 0
            with pytest.raises(ProviderHTTPError):
                await p._post_json("https://test.invalid", headers={}, payload={"model": "m"})
    asyncio.run(run())
    assert len(calls) == 2


def test_strict_invalid_judge_is_not_a_successful_deterministic_debate():
    from tests.test_thesis_debate import ScriptedProvider
    p = ScriptedProvider(["Caso alcista con crecimiento.", "Caso bajista con riesgo.", "No me decanto."])
    with pytest.raises(ValueError, match="invalid debate verdict"):
        asyncio.run(debate_thesis("EXEL", "tesis", provider=p, strict_provider=True, use_jev=False))


def test_deadline_cancels_member_and_never_runs_an_orphan():
    from app.llm.free_interactive import FreeInteractiveProvider
    from tests.test_chat_free_fallback import Fake
    p = Fake(delay=10)
    provider = FreeInteractiveProvider([p], total_timeout_seconds=.01)
    with pytest.raises(FreeLLMUnavailable):
        asyncio.run(provider.complete(LLMRequest([Message("user", "tesis")], task="red_team")))
    assert p.cancelled


def test_interactive_quota_does_not_block_background_jobs():
    from app.llm.factory import create_llm_provider
    calls = []
    def handle(req):
        calls.append(json.loads(req.content)["model"])
        return httpx.Response(429) if len(calls) <= 2 else httpx.Response(200, json=envelope())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            request = LLMRequest([Message("user", "tesis")], task="red_team")
            with pytest.raises(FreeLLMUnavailable):
                await create_free_interactive_provider(settings(), client=client).complete(request)
            background = create_llm_provider(settings(), client=client, max_retries=0)
            assert (await background.complete(request)).model == "deepseek-v4.1-flash-free"
    asyncio.run(run())
    assert calls == ["deepseek-v4.1-flash-free", "space-bunny-free", "deepseek-v4.1-flash-free"]


@pytest.mark.parametrize("config", [
    {"opencode_go_model": "paid"},
    {"opencode_go_fallback_model": "paid"},
    {"llm_model_overrides": {"chat": "paid"}},
])
def test_bad_chat_configuration_degrades_at_call_not_constructor(config):
    from app.llm.errors import ProviderDisabledError
    provider = create_chat_llm_provider(settings(**config))
    assert provider.name == "disabled"
    with pytest.raises(ProviderDisabledError):
        asyncio.run(provider.complete(LLMRequest([Message("user", "hola")], task="chat")))


def test_chat_primary_is_capped_at_the_shared_chat_budget_without_groq():
    provider = create_chat_llm_provider(settings(llm_timeout_seconds=120, llm_total_timeout_seconds=240))
    assert provider._timeout.read == 45
    assert provider._total_timeout_seconds == 45
