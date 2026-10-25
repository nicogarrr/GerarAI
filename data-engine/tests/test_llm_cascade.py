"""Cascada gratuita: orden, caida entre miembros, tope total y rutas por tarea."""

import asyncio
import logging

import httpx
import pytest

from app.core.config import Settings
from app.llm.adapters import DisabledProvider, OpenAICompatibleProvider
from app.llm.cascade import CascadeProvider
from app.llm.contracts import LLMRequest, Message
from app.llm.errors import ProviderHTTPError, ProviderRequestError, ProviderTransportError
from app.llm.factory import create_llm_provider

OK = {
    "id": "r1",
    "model": "m",
    "choices": [{"message": {"role": "assistant", "content": "hola"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def _request(**kw) -> LLMRequest:
    return LLMRequest(messages=[Message("user", "hola")], **kw)


def _member(name: str, handler, **kw) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key=f"key-{name}",
        base_url=f"https://{name}.test/v1",
        default_model=f"model-{name}",
        provider_name=name,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
        **kw,
    )


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, llm_provider="cascade", **kw)


def test_default_provider_is_unchanged_opencode() -> None:
    provider = create_llm_provider(Settings(_env_file=None, opencode_go_api_key="k"))
    assert provider.name == "opencode-go"


def test_cascade_members_follow_order_and_only_those_with_keys() -> None:
    full = create_llm_provider(
        _settings(gemini_api_key="g", openrouter_api_key="o", opencode_go_api_key="c")
    )
    assert isinstance(full, CascadeProvider)
    assert full.member_names == ["gemini", "openrouter", "opencode-go"]
    only_or = create_llm_provider(_settings(openrouter_api_key="o"))
    assert only_or.member_names == ["openrouter"]  # type: ignore[attr-defined]
    none = create_llm_provider(_settings())
    assert isinstance(none, DisabledProvider) and none.reason == "cascade_without_any_api_key"


def test_cascade_member_urls_models_and_capabilities() -> None:
    provider = create_llm_provider(_settings(gemini_api_key="g", openrouter_api_key="o"))
    gemini, openrouter = provider.members  # type: ignore[attr-defined]
    assert gemini._base_url == "https://generativelanguage.googleapis.com/v1beta/openai"  # noqa: SLF001
    assert gemini.model_router.resolve(_request()) == "gemini-3.8-flash"
    assert openrouter._base_url == "https://openrouter.ai/api/v1"  # noqa: SLF001
    assert openrouter.model_router.resolve(_request()) == "google/gemma-4-31b-it:free"
    assert provider.supported_capabilities == gemini.supported_capabilities


def test_task_routes_resolve_to_each_members_own_model() -> None:
    # Las rutas por tarea usan alias de OpenCode (space-bunny-free...): sin el
    # mapeo, el registro de alias los rechazaria en Gemini/OpenRouter.
    provider = create_llm_provider(
        _settings(gemini_api_key="g", openrouter_api_key="o", opencode_go_api_key="c")
    )
    gemini, openrouter, opencode = provider.members  # type: ignore[attr-defined]
    for task in ("cheap_extraction", "main_financial_analysis", "agentic_red_team", "no_such_task"):
        request = _request(task=task)
        assert gemini.model_router.resolve(request) == "gemini-3.8-flash"
        assert openrouter.model_router.resolve(request) == "google/gemma-4-31b-it:free"
    pinned = _request(model="space-bunny-free")
    assert gemini.model_router.resolve(pinned) == "gemini-3.8-flash"
    assert opencode.model_router.resolve(pinned) == "space-bunny-free"


def test_user_model_overrides_only_apply_to_opencode() -> None:
    provider = create_llm_provider(
        _settings(
            gemini_api_key="g",
            opencode_go_api_key="c",
            llm_model_overrides={"deepseek-v4.1-flash": "longcat-2.5-preview-free"},
        )
    )
    gemini, opencode = provider.members  # type: ignore[attr-defined]
    request = _request(task="cheap_extraction")
    assert opencode.model_router.resolve(request) == "longcat-2.5-preview-free"
    assert gemini.model_router.resolve(request) == "gemini-3.8-flash"


def test_falls_through_http_error_then_returns_next_members_answer(caplog) -> None:
    calls: list[str] = []

    def first(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(429, text="quota exceeded key-first")

    def second(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        assert request.headers["authorization"] == "Bearer key-second"
        return httpx.Response(200, json=OK)

    cascade = CascadeProvider([_member("first", first), _member("second", second)])
    with caplog.at_level(logging.WARNING):
        response = asyncio.run(cascade.complete(_request()))
    assert response.text == "hola" and response.provider == "second"
    assert calls == ["first.test", "second.test"]
    assert "first failed (ProviderHTTPError)" in caplog.text
    assert "key-first" not in caplog.text.replace("key-first-redacted", "") or "[REDACTED]" in caplog.text


def test_falls_through_transport_error_and_unreadable_body() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    def junk(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    ok = _member("ok", lambda request: httpx.Response(200, json=OK))
    cascade = CascadeProvider([_member("a", boom), _member("b", junk), ok])
    assert asyncio.run(cascade.complete(_request())).provider == "ok"


def test_all_members_failing_raises_the_last_error() -> None:
    cascade = CascadeProvider(
        [
            _member("a", lambda r: httpx.Response(500)),
            _member("b", lambda r: httpx.Response(403)),
        ]
    )
    with pytest.raises(ProviderHTTPError) as caught:
        asyncio.run(cascade.complete(_request()))
    assert caught.value.provider == "b" and caught.value.status_code == 403


def test_our_own_bad_request_is_not_retried_on_another_provider() -> None:
    class Bad(OpenAICompatibleProvider):
        async def complete(self, request):  # type: ignore[override]
            raise ProviderRequestError("mal construida")

    second_called = []
    bad = Bad(api_key="k", base_url="https://bad.test/v1", default_model="m", provider_name="bad")
    ok = _member("ok", lambda r: second_called.append(1) or httpx.Response(200, json=OK))
    with pytest.raises(ProviderRequestError):
        asyncio.run(CascadeProvider([bad, ok]).complete(_request()))
    assert second_called == []


def test_total_timeout_bounds_the_whole_cascade() -> None:
    class Slow(OpenAICompatibleProvider):
        async def complete(self, request):  # type: ignore[override]
            await asyncio.sleep(5)

    slow = Slow(api_key="k", base_url="https://slow.test/v1", default_model="m", provider_name="slow")
    cascade = CascadeProvider([slow], total_timeout_seconds=0.05)
    with pytest.raises(ProviderTransportError) as caught:
        asyncio.run(cascade.complete(_request()))
    assert caught.value.reason == "timeout"


def test_empty_cascade_and_bad_timeout_are_rejected() -> None:
    with pytest.raises(ValueError):
        CascadeProvider([])
    with pytest.raises(ValueError):
        CascadeProvider([_member("a", lambda r: httpx.Response(200, json=OK))], total_timeout_seconds=0)


def test_cost_guards_fail_closed_with_the_real_cascade() -> None:
    from app.services.llm_proposal_runner import paid_model_risk as proposal_risk

    provider = create_llm_provider(
        _settings(gemini_api_key="g", openrouter_api_key="o", opencode_go_api_key="c")
    )
    resolved = provider.model_router.resolve(_request(task="cheap_extraction"))  # type: ignore[attr-defined]
    assert resolved == (
        "cascade[gemini=gemini-3.8-flash,openrouter=google/gemma-4-31b-it:free,"
        "opencode-go=deepseek-v4.1-flash]"
    )
    assert proposal_risk(provider) == "modelo_no_gratuito"
    assert proposal_risk(provider, request=_request(model="space-bunny-free")) == "modelo_no_gratuito"


def test_http_400_still_tries_the_next_member_but_request_errors_do_not() -> None:
    calls: list[str] = []

    def bad(request: httpx.Request) -> httpx.Response:
        calls.append("a")
        return httpx.Response(400, text="bad")

    def ok(request: httpx.Request) -> httpx.Response:
        calls.append("b")
        return httpx.Response(200, json=OK)

    cascade = CascadeProvider([_member("a", bad), _member("b", ok)])
    assert asyncio.run(cascade.complete(_request())).provider == "b"
    assert calls == ["a", "b"]
