"""No-network proof of paid-tier guard and real request routing."""
import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.chat_provider import GEMINI_MODEL, GEMINI_MODEL_2, create_chat_llm_provider
from app.llm.contracts import LLMRequest, Message
from app.llm.free_interactive import FreeLLMUnavailable, create_free_interactive_provider


def cfg(**kw):
    values = dict(llm_enabled=True, llm_provider="opencode-go", opencode_go_api_key="fake",
                  chat_go_subscription_enabled=False,
                  opencode_go_model="deepseek-v4.1-flash-free",
                  gemini_api_key="fake", gemini_chat_fallback_enabled=True,
                  gemini_free_plan_confirmed=True, groq_chat_fallback_enabled=False)
    values.update(kw)
    return Settings(_env_file=None, **values)


def response(text="Respuesta en español con fuentes."):
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2}}


@pytest.mark.parametrize("kind", ["chat", "debate"])
def test_two_opencode_429_then_gemini_without_groq(kind):
    seen = []
    def handle(req):
        body = json.loads(req.content)
        seen.append((req.url.host, body["model"]))
        if req.url.host != "generativelanguage.googleapis.com":
            return httpx.Response(429)
        assert body["model"] == GEMINI_MODEL
        assert body["reasoning_effort"] == "low"
        return httpx.Response(200, json=response())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            factory = create_chat_llm_provider if kind == "chat" else create_free_interactive_provider
            provider = factory(cfg(), client=client)
            out = await provider.complete(LLMRequest([Message("user", "hola")], task="chat" if kind == "chat" else "red_team"))
            assert out.provider == "gemini"
            assert out.model == GEMINI_MODEL
    asyncio.run(run())
    free_calls = (
        ["deepseek-v4.1-flash-free"]
        if kind == "chat"
        else ["deepseek-v4.1-flash-free", "space-bunny-free"]
    )
    assert [model for _, model in seen] == [*free_calls, GEMINI_MODEL]


@pytest.mark.parametrize("kind", ["chat", "debate"])
def test_no_billing_confirmation_means_no_gemini_request(kind):
    factory = create_chat_llm_provider if kind == "chat" else create_free_interactive_provider
    with pytest.raises(ValueError, match="verified free plan"):
        factory(cfg(gemini_free_plan_confirmed=False))


def test_debate_all_429_error_and_cooldown_covers_gemini():
    seen = []
    def handle(req):
        seen.append(json.loads(req.content)["model"])
        return httpx.Response(429)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = create_free_interactive_provider(cfg(), client=client)
            for _ in range(2):
                with pytest.raises(FreeLLMUnavailable, match="modelo configurado ha agotado su cuota"):
                    await provider.complete(LLMRequest([Message("user", "tesis")], task="red_team"))
    asyncio.run(run())
    assert seen == ["deepseek-v4.1-flash-free", "space-bunny-free", GEMINI_MODEL, GEMINI_MODEL_2]


def test_second_gemini_model_after_first_quota():
    seen = []
    def handle(req):
        model = json.loads(req.content)["model"]
        seen.append(model)
        return httpx.Response(200, json=response()) if model == GEMINI_MODEL_2 else httpx.Response(429)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            out = await create_chat_llm_provider(cfg(), client=client).complete(LLMRequest([Message("user", "hola")], task="chat"))
            assert out.model == GEMINI_MODEL_2
    asyncio.run(run())
    assert seen[-2:] == [GEMINI_MODEL, GEMINI_MODEL_2]
