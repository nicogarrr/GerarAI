import asyncio
from functools import wraps

import httpx
import pytest

from app.core.config import Settings
from app.llm.chat_provider import GROQ_MODEL, ChatFallbackProvider, create_chat_llm_provider
from app.llm.contracts import LLMRequest, LLMResponse, Message, Usage
from app.llm.errors import ProviderHTTPError, ProviderRequestError, ProviderTransportError


def run_async(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapped


def response(text="válida", *, model="primary", provider="opencode-go", finish="stop"):
    return LLMResponse(Message("assistant", text), Usage(), model, provider, finish_reason=finish)


class Fake:
    name = "fake"
    supported_capabilities = frozenset({"text", "structured_output"})
    model_router = None
    def __init__(self, value=None, delay=0):
        self.value = value or response()
        self.delay = delay
        self.calls = []
        self.cancelled = False
    async def complete(self, request):
        self.calls.append(request)
        try:
            await asyncio.sleep(self.delay)
            if isinstance(self.value, Exception): raise self.value
            return self.value
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@run_async
async def test_fast_primary_never_calls_backup():
    p, b = Fake(), Fake()
    out = await ChatFallbackProvider(p, b, total=.3, delay=.1).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert out.provider == "opencode-go" and not b.calls


@run_async
async def test_429_uses_independent_provider_with_pinned_model():
    p, b = Fake(ProviderHTTPError("opencode-go", 429)), Fake(response(model=GROQ_MODEL, provider="groq"))
    out = await ChatFallbackProvider(p, b, total=.3, delay=.1).complete(LLMRequest([Message("user", "hola")], task="chat", model="deepseek-v4.1-flash-free"))
    assert out.provider == "groq" and b.calls[0].model == GROQ_MODEL


@run_async
async def test_slow_primary_within_its_budget_wins_and_backup_never_starts():
    # Sin carrera (2026-10-27): el respaldo solo arranca si Go falla o agota su plazo.
    p, b = Fake(delay=.08), Fake(delay=.01)
    out = await ChatFallbackProvider(p, b, total=.3, delay=.2).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert out.provider == "opencode-go" and not b.calls


@run_async
async def test_backup_wins_then_primary_is_cancelled():
    p, b = Fake(delay=.2), Fake(response(model=GROQ_MODEL, provider="groq"))
    out = await ChatFallbackProvider(p, b, total=.3, delay=.01).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert out.provider == "groq" and p.cancelled


@run_async
async def test_deadline_cancels_both():
    p, b = Fake(delay=1), Fake(delay=1)
    with pytest.raises(ProviderTransportError):
        await ChatFallbackProvider(p, b, total=.05, delay=.01).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert p.cancelled and b.cancelled


@run_async
async def test_our_request_error_does_not_trigger_another_provider():
    p, b = Fake(ProviderRequestError("invalid")), Fake()
    with pytest.raises(ProviderRequestError):
        await ChatFallbackProvider(p, b).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert not b.calls


@run_async
async def test_nonchat_task_never_calls_groq():
    p, b = Fake(), Fake()
    await ChatFallbackProvider(p, b).complete(LLMRequest([Message("user", "hola")], task="deep_thesis"))
    assert not b.calls


@run_async
async def test_truncated_primary_does_not_win_over_valid_backup():
    p, b = Fake(response(finish="length")), Fake(response(model=GROQ_MODEL, provider="groq"))
    out = await ChatFallbackProvider(p, b).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert out.provider == "groq"


def test_free_fallback_model_must_be_owner_approved():
    # La pata free de la cadena (Go -> OpenCode free -> Gemini) solo acepta
    # modelos free verificados: uno desconocido rompe la construccion.
    cfg = dict(llm_enabled=True, opencode_go_api_key="synthetic",
               opencode_free_model="paid-unknown")
    with pytest.raises(ValueError, match="owner-approved free model"):
        create_chat_llm_provider(Settings(**cfg))


def test_free_fallback_off_without_go_key_or_flag():
    # Sin clave Go no hay pata free; con el flag en false tampoco, y en
    # ambos casos la construccion no rompe.
    base = dict(llm_enabled=True, chat_go_subscription_enabled=False,
                opencode_go_model="deepseek-v4.1-flash-free")
    assert create_chat_llm_provider(Settings(**base, opencode_go_api_key="synthetic")).name == "opencode-go"
    cfg = dict(llm_enabled=True, opencode_go_api_key="synthetic",
               opencode_free_chat_fallback_enabled=False)
    provider = create_chat_llm_provider(Settings(**cfg))
    assert getattr(provider, "backup", None) is None


@run_async
async def test_real_adapter_envelope_is_opencode_free_with_go_session():
    # Go agota cuota (429 semanal): el respaldo es la capa free de Zen con
    # la MISMA clave Go, cabecera de sesion y el modelo free fijado.
    seen = []
    def handler(req):
        import json
        body = json.loads(req.content)
        seen.append(body)
        if req.url.host == "go.invalid":
            return httpx.Response(429, json={"error": {"message": "GoUsageLimitError: weekly usage limit reached"}})
        assert req.url.host == "free.invalid"
        assert req.headers["x-opencode-session"] == "cavaai-prod"
        assert req.headers["authorization"] == "Bearer synthetic"
        assert body["model"] == "deepseek-v4.1-flash-free" and body["reasoning_effort"] == "low"
        assert "response_format" not in body
        return httpx.Response(200, json={"model": "deepseek-v4.1-flash-free", "choices": [{"message": {"role": "assistant", "content": "Respuesta factual"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cfg = Settings(llm_enabled=True, opencode_go_api_key="synthetic",
                       chat_go_subscription_base_url="https://go.invalid/v1",
                       opencode_free_base_url="https://free.invalid/v1",
                       llm_max_retries=0)
        out = await create_chat_llm_provider(cfg, client=client).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert out.provider == "opencode-free" and len(seen) == 2
    assert seen[0]["model"] == "deepseek-v4.1-flash"  # primario Go suscripcion


@run_async
async def test_slow_valid_primary_never_touches_a_failing_backup():
    p, b = Fake(delay=.08), Fake(ProviderHTTPError("groq", 429))
    out = await ChatFallbackProvider(p, b, total=.3, delay=.2).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert out.provider == "opencode-go" and not b.calls


@run_async
async def test_external_cancel_collects_both_tasks():
    p, b = Fake(delay=1), Fake(delay=1)
    task = asyncio.create_task(ChatFallbackProvider(p, b, total=2, delay=.01).complete(LLMRequest([Message("user", "hola")], task="chat")))
    await asyncio.sleep(.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert p.cancelled and b.cancelled


@run_async
async def test_backup_may_reason_about_positions_but_keeps_truth_rules():
    p, b = Fake(ProviderHTTPError("opencode-go", 429)), Fake()
    await ChatFallbackProvider(p, b).complete(LLMRequest([Message("user", "hola")], task="chat"))
    instruction = b.calls[0].messages[-1].content
    assert "Puedes opinar y razonar" in instruction
    assert "No des asesoramiento" not in instruction and "educativo" not in instruction
    assert "No añadas porcentajes" in instruction
    for rule in ("prosa plana", "sin LaTeX", "120 palabras", "No escribas cifras, rangos", "No uses corchetes"):
        assert rule in instruction


@run_async
async def test_tools_never_go_to_backup():
    from app.llm.contracts import ToolDefinition
    p, b = Fake(), Fake()
    await ChatFallbackProvider(p, b).complete(LLMRequest([Message("user", "hola")], task="chat", tools=(ToolDefinition("read"),)))
    assert not b.calls


def test_disabled_flag_keeps_primary_unchanged():
    provider = create_chat_llm_provider(Settings(
        llm_enabled=True, chat_go_subscription_enabled=False,
        opencode_go_model="deepseek-v4.1-flash-free", opencode_go_api_key="synthetic",
    ))
    assert provider.name == "opencode-go"


@run_async
async def test_paid_primary_override_rejected_before_network():
    seen = []
    def handler(req):
        seen.append(req)
        raise AssertionError("network must not run")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cfg = Settings(llm_enabled=True, chat_go_subscription_enabled=False, opencode_go_api_key="synthetic", opencode_go_model="paid-unknown", llm_model_overrides={"chat": "paid-unknown"}, groq_api_key="synthetic", groq_chat_fallback_enabled=True, groq_free_plan_confirmed=True, groq_zdr_confirmed=True)
        from app.llm.errors import ProviderDisabledError
        with pytest.raises(ProviderDisabledError, match="not_verified_free"):
            await create_chat_llm_provider(cfg, client=client).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert not seen


@pytest.mark.parametrize("text", [
    "Para tu cartera, te recomiendo comprar más AAA y vender BBB.",
    "You should buy AAA and sell BBB.", "Asigne un 60% a acciones.",
])
@run_async
async def test_advice_wording_is_no_longer_rejected_by_the_provider(text):
    p, b = Fake(ProviderHTTPError("opencode-go", 429)), Fake(response(text, model=GROQ_MODEL, provider="groq"))
    out = await ChatFallbackProvider(p, b).complete(LLMRequest([Message("user", "sintético")], task="chat"))
    assert out.text == text


@run_async
async def test_structured_context_backup_is_explicit_and_preserved():
    p, b = Fake(ProviderHTTPError("opencode-go", 429)), Fake(response("Datos sintéticos de la prueba.", model=GROQ_MODEL, provider="groq"))
    req = LLMRequest([Message("system", "Contrato estructurado"), Message("user", "Pregunta, ticker AAA, secciones y fuentes SINTÉTICAS")], task="main_financial_analysis")
    out = await ChatFallbackProvider(p, b).complete(req)
    assert out.provider == "groq"
    assert tuple(b.calls[0].messages[:-1]) == tuple(req.messages)
    assert "Puedes opinar y razonar" in b.calls[0].messages[-1].content

@pytest.mark.parametrize("bad", ["not_json", "citation", "language"])
@run_async
async def test_invalid_fast_backup_keeps_valid_slow_primary_through_synthesis(bad):
    import json

    from app.services.chat_synthesis_service import ChatSynthesisService
    from tests.test_chat_synthesis_service import _baseline, _llm_payload
    payload = _llm_payload()
    valid = json.dumps(payload)
    if bad == "not_json":
        invalid = "Texto español correcto pero no JSON"
    elif bad == "citation":
        invalid = json.dumps(_llm_payload(citations=["financial_fact:999"]))
    else:
        for section in payload["sections"]:
            section["body"] = "The company is profitable and the earnings are growing because the market is strong."
        invalid = json.dumps(payload)
    p = Fake(response(valid, model="valid-primary"), delay=.08)
    b = Fake(response(invalid, model=GROQ_MODEL, provider="groq"), delay=.01)
    provider = ChatFallbackProvider(p, b, total=.4, delay=.25)
    result = await ChatSynthesisService(provider).synthesize(
        question="Resumen sintético", ticker="AAA", baseline=_baseline(), enable_debate=False,
    )
    assert result.model == "valid-primary"
    assert result.llm_trace["citation_verification"] is True
    # Go respondio dentro de su plazo: el respaldo (invalido) ni se llama.
    assert not p.cancelled and not b.calls


@run_async
async def test_invalid_fast_general_backup_preserves_valid_slow_primary():
    from app.schemas import ChatResponse
    from app.services.chat_synthesis_service import ChatSynthesisService
    p = Fake(response("Respuesta breve en español.", model="valid-primary"), delay=.08)
    b = Fake(response("The company is profitable and the earnings are growing.", model=GROQ_MODEL, provider="groq"), delay=.01)
    result = await ChatSynthesisService(ChatFallbackProvider(p, b, total=.4, delay=.25)).synthesize_general(
        question="Cuéntame algo", baseline=ChatResponse(answer="", sources=[]),
    )
    assert result.model == "valid-primary" and not p.cancelled and not b.calls


def test_candidate_validation_context_is_per_call_not_shared():
    provider = ChatFallbackProvider(Fake(), Fake())
    a = provider.with_candidate_validator(lambda r: None)
    b = provider.with_candidate_validator(lambda r: None)
    assert a is not b and a.validator is not b.validator and provider.validator is None


@run_async
async def test_primary_language_retry_hint_survives_backup_failure_without_double_record(monkeypatch):
    from app.schemas import ChatResponse
    from app.services.chat_synthesis_service import ChatSynthesisService
    class Recovering(Fake):
        async def complete(self, request):
            self.calls.append(request)
            if len(self.calls) == 1:
                return response("The company is profitable and the earnings are growing.")
            return response("Respuesta válida en español.", model="recovered-primary")
    records = []
    monkeypatch.setattr("app.services.chat_synthesis_service.BudgetController.record", lambda self, *args: records.append(args))
    monkeypatch.setattr("app.services.chat_synthesis_service.BudgetController.can_spend", lambda *args: True)
    p, b = Recovering(), Fake(ProviderHTTPError("groq", 429))
    result = await ChatSynthesisService(ChatFallbackProvider(p, b, total=.3, delay=.001)).synthesize_general(
        question="Cuéntame algo", baseline=ChatResponse(answer="", sources=[]), db=object(),
    )
    assert result.model == "recovered-primary"
    assert len(p.calls) == 2 and len(b.calls) == 1
    from app.services.llm_output_guard import RETRY_HINT
    assert RETRY_HINT in p.calls[1].messages[0].content
    assert RETRY_HINT not in p.calls[0].messages[0].content
    assert len(records) == 2  # rejected first response and valid second, once each


@run_async
async def test_primary_bad_language_cannot_cancel_valid_backup():
    from app.schemas import ChatResponse
    from app.services.chat_synthesis_service import ChatSynthesisService
    p = Fake(response("The company is profitable and the earnings are growing."))
    b = Fake(response("Respuesta válida en español.", model=GROQ_MODEL, provider="groq"), delay=.03)
    result = await ChatSynthesisService(ChatFallbackProvider(p, b, total=.3, delay=.001)).synthesize_general(
        question="Cuéntame algo", baseline=ChatResponse(answer="", sources=[]),
    )
    assert result.model == GROQ_MODEL and len(p.calls) == 1 and not b.cancelled


def test_default_primary_budget_is_two_thirds_of_the_total():
    # Ya no es una ventaja de 2 s: es el plazo de Go antes de pasar al respaldo.
    provider = ChatFallbackProvider(Fake(), Fake())
    assert provider.delay == 30
    assert provider.with_candidate_validator(lambda _: None).delay == 30


@run_async
async def test_free_tier_502_starts_backup_and_keeps_candidate_guards():
    from app.llm.errors import ProviderResponseError
    primary = Fake(ProviderHTTPError('opencode-go', 502))
    backup = Fake(response('Texto sintético.', model=GROQ_MODEL, provider='groq'))
    def reject(_): raise ValueError('unverified citation')
    with pytest.raises(ProviderResponseError, match='unverified citation'):
        await ChatFallbackProvider(primary, backup, validator=reject).complete(
            LLMRequest([Message('user', 'Pregunta sintética')], task='chat'))
    assert len(backup.calls) == 1
    instruction = backup.calls[0].messages[-1].content
    assert 'No atribuyas opiniones a un autor' in instruction
    assert 'No añadas porcentajes' in instruction
    assert 'No deduzcas una deuda neta alta' in instruction


@run_async
async def test_502_backup_still_rejects_unsupported_doctrine_numbers_and_advice():
    from app.schemas import ChatResponse
    from app.services.chat_synthesis_service import ChatSynthesisService
    primary = Fake(ProviderHTTPError('opencode-go', 502))
    backup = Fake(response('Buffett exige un margen de seguridad del 30%.', model=GROQ_MODEL, provider='groq'))
    result = await ChatSynthesisService(ChatFallbackProvider(primary, backup)).synthesize_general(
        question='Explica el margen de seguridad', baseline=ChatResponse(answer='', sources=[]))
    assert result.model == 'fallback'


@run_async
async def test_502_backup_advice_without_invented_facts_now_passes():
    from app.schemas import ChatResponse
    from app.services.chat_synthesis_service import ChatSynthesisService
    primary = Fake(ProviderHTTPError('opencode-go', 502))
    text = 'Yo no añadiría más a esa posición: ya pesa mucho y el negocio aún no genera caja. Mantendría y vigilaría la deuda.'
    backup = Fake(response(text, model=GROQ_MODEL, provider='groq'))
    result = await ChatSynthesisService(ChatFallbackProvider(primary, backup)).synthesize_general(
        question='¿Qué harías con el margen de seguridad?', baseline=ChatResponse(answer='', sources=[]))
    assert result.model == GROQ_MODEL and result.answer == text


@pytest.mark.parametrize('invented', [
    'Yo compraría más: el margen de seguridad ideal es del 30% según el informe anual.',
    'Yo venderia: Warren Buffett ha reiterado que hay que vender con deuda neta alta.',
    'Yo mantendría: la empresa gana 12,45 dólares por acción.',
])
@run_async
async def test_502_backup_advice_with_invented_facts_is_still_rejected(invented):
    from app.schemas import ChatResponse
    from app.services.chat_synthesis_service import ChatSynthesisService
    primary = Fake(ProviderHTTPError('opencode-go', 502))
    backup = Fake(response(invented, model=GROQ_MODEL, provider='groq'))
    result = await ChatSynthesisService(ChatFallbackProvider(primary, backup)).synthesize_general(
        question='¿Qué opinas del margen de seguridad?', baseline=ChatResponse(answer='', sources=[]))
    assert result.model == 'fallback'


def _chain(groq_value, gemini_value):
    p = Fake(ProviderHTTPError("opencode-go", 502))
    return p, Fake(groq_value), Fake(gemini_value)


@run_async
async def test_chain_valid_groq_never_calls_gemini_and_uses_pinned_model_and_prompt():
    p, g, m = _chain(response("ok groq", model=GROQ_MODEL, provider="groq"), response("ok gemini", model="x", provider="gemini"))
    out = await ChatFallbackProvider(p, g, backup2=m).complete(LLMRequest([Message("user", "hola")], task="chat", model="deepseek-v4.1-flash-free"))
    assert out.provider == "groq" and not m.calls
    assert g.calls[0].model == GROQ_MODEL and "prosa plana" in g.calls[0].messages[-1].content


@run_async
async def test_chain_groq_failure_tries_35_then_38_with_pinned_models_and_prompt():
    from app.llm.chat_provider import GEMINI_MODELS
    p, g, m = _chain(ProviderHTTPError("groq", 429), ProviderHTTPError("gemini", 429))
    with pytest.raises(ProviderHTTPError):
        await ChatFallbackProvider(p, g, backup2=m).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert len(g.calls) == 1 and g.calls[0].model == GROQ_MODEL
    assert [c.model for c in m.calls] == list(GEMINI_MODELS) and GEMINI_MODELS == ("gemini-3.5-flash-lite", "gemini-3.8-flash")
    assert all("prosa plana" in c.messages[-1].content for c in m.calls)


@run_async
async def test_chain_groq_429_then_35_valid_never_reaches_38():
    from app.llm.chat_provider import GEMINI_MODEL
    p, g, m = _chain(ProviderHTTPError("groq", 429), response("ok gemini", model=GEMINI_MODEL, provider="gemini"))
    out = await ChatFallbackProvider(p, g, backup2=m).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert out.provider == "gemini" and [c.model for c in m.calls] == [GEMINI_MODEL]


@run_async
async def test_chain_groq_and_35_rejected_then_38_accepted():
    from app.llm.chat_provider import GEMINI_MODEL, GEMINI_MODEL_2
    p, g, m = _chain(response("MALA", model=GROQ_MODEL, provider="groq"), None)
    class Seq(Fake):
        async def complete(self, request):
            self.calls.append(request)
            return response("MALA" if request.model == GEMINI_MODEL else "BUENA", model=request.model, provider="gemini")
    m = Seq()
    def only_good(resp):
        if resp.text != "BUENA":
            raise ValueError("rejected")
    out = await ChatFallbackProvider(p, g, backup2=m, validator=only_good).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert out.text == "BUENA" and out.model == GEMINI_MODEL_2 and len(g.calls) == 1 and len(m.calls) == 2


@run_async
async def test_chain_groq_rejected_by_validator_falls_to_gemini():
    from app.llm.chat_provider import GEMINI_MODEL
    p, g, m = _chain(response("MALA", model=GROQ_MODEL, provider="groq"), response("BUENA", model=GEMINI_MODEL, provider="gemini"))
    def only_good(resp):
        if resp.text != "BUENA":
            raise ValueError("rejected")
    out = await ChatFallbackProvider(p, g, backup2=m, validator=only_good).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert out.text == "BUENA" and len(g.calls) == 1 and len(m.calls) == 1


@run_async
async def test_chain_every_candidate_still_goes_through_the_truth_validator():
    from app.llm.chat_provider import GEMINI_MODEL
    from app.llm.errors import ProviderResponseError
    p, g, m = _chain(response("Rentabilidad del 30,55% segun el informe", model=GROQ_MODEL, provider="groq"), response("Otra cifra inventada 12,45", model=GEMINI_MODEL, provider="gemini"))
    def reject(resp):
        raise ValueError("ungrounded")
    with pytest.raises(ProviderResponseError, match="ungrounded"):
        await ChatFallbackProvider(p, g, backup2=m, validator=reject).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert len(m.calls) == 2 and len(g.calls) == 1


@run_async
async def test_chain_without_gemini_behaves_as_before():
    from app.llm.errors import ProviderResponseError
    p, g = Fake(ProviderHTTPError("opencode-go", 502)), Fake(ProviderHTTPError("groq", 429))
    with pytest.raises((ProviderHTTPError, ProviderResponseError)):
        await ChatFallbackProvider(p, g).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert g.calls[0].model == GROQ_MODEL


def _gemini_cfg(**over):
    cfg = dict(
        llm_enabled=True, chat_go_subscription_enabled=False,
        opencode_go_model="deepseek-v4.1-flash-free", opencode_go_api_key="synthetic",
        groq_api_key="synthetic", groq_chat_fallback_enabled=True,
        groq_free_plan_confirmed=True, groq_zdr_confirmed=True,
    )
    cfg.update(over)
    return Settings(**cfg)


def test_gemini_disabled_by_default_and_factory_unchanged():
    # Sin Gemini ni pata free (chat_go_subscription_enabled=False en esta
    # config) la factory devuelve el primario a secas.
    assert create_chat_llm_provider(_gemini_cfg()).name == "opencode-go"


@pytest.mark.parametrize("missing", ["gemini_api_key", "gemini_free_plan_confirmed"])
def test_gemini_factory_is_fail_closed(missing):
    cfg = dict(gemini_chat_fallback_enabled=True, gemini_api_key="synthetic", gemini_free_plan_confirmed=True)
    cfg[missing] = None if missing.endswith("key") else False
    with pytest.raises(ValueError, match="Gemini chat requires"):
        create_chat_llm_provider(_gemini_cfg(**cfg))


def test_gemini_enabled_builds_pinned_free_model_backup():
    from app.llm.chat_provider import GEMINI_MODEL, GEMINI_MODEL_2
    prov = create_chat_llm_provider(_gemini_cfg(gemini_chat_fallback_enabled=True, gemini_api_key="synthetic", gemini_free_plan_confirmed=True))
    assert prov.backup is not None and prov.backup.name == "gemini"
    assert prov.backup_model == GEMINI_MODEL
    assert prov.extra_backups == ((prov.backup, GEMINI_MODEL_2),)
    assert GEMINI_MODEL == "gemini-3.5-flash-lite"


@run_async
async def test_cjk_retry_goes_straight_to_backup_chain():
    """El reintento del guard tras rechazo CJK no repite el primario lento:
    va directo a la cadena de respaldo (Groq) con el timeout total."""
    p, b = Fake(), Fake(response("recuperado", provider="groq"))
    provider = ChatFallbackProvider(p, b, total=.3, delay=.1)
    out = await provider.complete_cjk_retry(LLMRequest([Message("user", "hola")], task="chat"))
    assert out.provider == "groq"
    assert not p.calls, "el primario no participa en el reintento CJK"
    assert len(b.calls) == 1
    assert b.calls[0].model == GROQ_MODEL


@run_async
async def test_cjk_retry_respects_total_timeout():
    p, b = Fake(), Fake(delay=5)
    provider = ChatFallbackProvider(p, b, total=.05, delay=.01)
    try:
        await provider.complete_cjk_retry(LLMRequest([Message("user", "hola")], task="chat"))
        raise AssertionError("debe agotar el timeout total")
    except ProviderTransportError:
        pass


@run_async
async def test_429_cooldown_skips_primary_on_next_chat():
    p, b = Fake(ProviderHTTPError("fake", 429)), Fake(response(model=GROQ_MODEL, provider="groq"))
    chat = ChatFallbackProvider(p, b, total=.3, delay=.1)
    await chat.complete(LLMRequest([Message("user", "hola")], task="chat"))
    await chat.complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert len(p.calls) == 1 and len(b.calls) == 2


@run_async
async def test_cooling_backup_is_skipped_for_next_member():
    p = Fake(ProviderHTTPError("opencode-go", 429))
    groq = Fake(ProviderHTTPError("groq", 429))
    groq.name = "groq"
    gem = Fake(response(model="gemini-3.5-flash-lite", provider="gemini"))
    gem.name = "gemini"
    chat = ChatFallbackProvider(p, groq, total=.5, delay=.01, backup2=gem)
    await chat.complete(LLMRequest([Message("user", "hola")], task="chat"))
    await chat.complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert len(groq.calls) == 1 and len(gem.calls) == 2


@run_async
async def test_extra_openrouter_member_is_last_resort():
    p = Fake(ProviderHTTPError("opencode-go", 429))
    groq = Fake(ProviderHTTPError("groq", 429))
    groq.name = "groq"
    orr = Fake(response(model="x:free", provider="openrouter"))
    orr.name = "openrouter"
    out = await ChatFallbackProvider(p, groq, total=.5, delay=.01, extra_backups=((orr, "x:free"),)).complete(LLMRequest([Message("user", "hola")], task="chat"))
    assert out.provider == "openrouter" and orr.calls[0].model == "x:free"


@run_async
async def test_fallback_trail_names_failed_members_without_messages_and_is_not_degraded():
    """SINTETICO: el miembro que respondio queda en provider/model y los que fallaron en fallback_trail."""
    p, b = Fake(ProviderHTTPError("opencode-go", 429)), Fake(response(model=GROQ_MODEL, provider="groq"))
    out = await ChatFallbackProvider(p, b, total=.3, delay=.1).complete(
        LLMRequest([Message("user", "hola")], task="chat", model="deepseek-v4.1-flash-free"))
    assert out.provider == "groq" and not out.degraded and out.warnings == ()
    assert out.fallback_trail == ("fake:?:ProviderHTTPError429",)


@run_async
async def test_fallback_trail_lists_each_failed_backup_and_empty_for_primary():
    primary_ok = await ChatFallbackProvider(Fake(), Fake(), total=.3, delay=.1).complete(
        LLMRequest([Message("user", "hola")], task="chat"))
    assert primary_ok.fallback_trail == ()
    p = Fake(ProviderHTTPError("opencode-go", 500))
    b = Fake(ProviderHTTPError("groq", 503))
    b2 = Fake(response(model="gemini-x", provider="gemini"))
    out = await ChatFallbackProvider(p, b, total=2, delay=.05, backup2=b2).complete(
        LLMRequest([Message("user", "hola")], task="chat"))
    assert out.provider == "gemini"
    assert out.fallback_trail[0].startswith("fake:") and "ProviderHTTPError500" in out.fallback_trail[0]
    assert any("ProviderHTTPError503" in t for t in out.fallback_trail)


@run_async
async def test_fallback_trail_labels_a_primary_out_of_budget_as_timeout():
    """Go agota su plazo: se cancela y solo entonces responde el respaldo."""
    slow = Fake(delay=5)
    out = await ChatFallbackProvider(slow, Fake(response(model=GROQ_MODEL, provider="groq")), total=2, delay=.05).complete(
        LLMRequest([Message("user", "hola")], task="chat"))
    assert out.provider == "groq" and slow.cancelled
    assert out.fallback_trail == ("fake:?:timeout",)
    assert not any("TimeoutError" in t for t in out.fallback_trail)
