"""Respaldo SOLO si falla OpenCode Go, nunca en carrera, y siempre etiquetado.

Decision del dueno (2026-11-01): la cadena de plataforma es OpenCode Go ->
OpenCode free (deepseek, /zen/v1, misma clave Go) -> Gemini. Los respaldos
entran unicamente despues de un error o del plazo agotado de Go; la
respuesta lo dice («Respondido por respaldo (...) porque OpenCode Go
falló: ...») y el flag a false los apaga del todo.
"""

from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.llm.chat_provider import (
    GO_SUBSCRIPTION_PROVIDER,
    GROQ_MODEL,
    ChatFallbackProvider,
    _openrouter_backup,
    create_chat_llm_provider,
    fallback_notice,
)
from app.llm.contracts import LLMRequest, LLMResponse, Message, Usage
from app.llm.errors import ProviderHTTPError
from app.llm.free_interactive import FreeInteractiveProvider, create_free_interactive_provider
from app.llm.tenant_config import TenantLLMConfig, tenant_llm_config_scope
from app.schemas import ChatResponse
from app.services.chat_synthesis_service import ChatSynthesisService


def _settings(**over) -> Settings:
    base: dict = {
        "llm_enabled": True,
        "llm_provider": "opencode-go",
        "opencode_go_api_key": "sk-sintetica",
        "groq_api_key": "gsk",
        "groq_free_plan_confirmed": True,
        "groq_zdr_confirmed": True,
        "gemini_api_key": "gm",
        "gemini_free_plan_confirmed": True,
        "openrouter_api_key": "or",
    }
    base.update(over)
    return Settings(_env_file=None, **base)  # pyright: ignore[reportCallIssue]


def _resp(text="Respuesta breve en español.", *, model="deepseek-v4.1-flash", provider=GO_SUBSCRIPTION_PROVIDER):
    return LLMResponse(Message("assistant", text), Usage(), model, provider, finish_reason="stop")


class _Fake:
    supported_capabilities = frozenset({"text", "structured_output"})
    model_router = None

    def __init__(self, value, *, name=GO_SUBSCRIPTION_PROVIDER, delay=0.0):
        self.name = name
        self.value = value
        self.delay = delay
        self.calls = 0
        self.cancelled = False

    async def complete(self, request):
        self.calls += 1
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _chat(primary, backup, *, total=1.0, delay=0.3):
    return ChatFallbackProvider(primary, backup, total=total, delay=delay)


def _run(coro):
    return asyncio.run(coro)


REQ = LLMRequest([Message("user", "hola")], task="chat")


# --- Configuracion: auto = solo si falla Go (con clave); false = apagado ---


def test_auto_con_claves_deja_los_respaldos_listos_para_cuando_falle_go():
    settings = _settings()
    assert settings.groq_chat_fallback_enabled is None
    assert settings.groq_chat_fallback_active is True
    assert settings.gemini_chat_fallback_active is True
    assert settings.openrouter_chat_fallback_active is True
    chat = create_chat_llm_provider(settings)
    assert isinstance(chat, ChatFallbackProvider)
    # Sin carrera: Go tiene 2/3 del presupuesto antes de que arranque nada.
    assert chat.delay == settings.chat_total_timeout_seconds * 2 / 3


def test_auto_sin_claves_externas_queda_la_pata_free_con_la_clave_go():
    settings = _settings(groq_api_key=None, gemini_api_key=None, openrouter_api_key=None)
    assert settings.groq_chat_fallback_active is False
    assert settings.gemini_chat_fallback_active is False
    assert settings.openrouter_chat_fallback_active is False
    # La pata free usa la misma clave Go (gasto 0): entra en modo auto.
    chat = create_chat_llm_provider(settings)
    assert getattr(chat, "backup", None) is not None
    assert chat.backup.name == "opencode-free"


def test_sin_ningun_respaldo_disponible_queda_el_primario():
    settings = _settings(
        gemini_api_key=None,
        opencode_free_chat_fallback_enabled=False,
    )
    assert getattr(create_chat_llm_provider(settings), "backup", None) is None


def test_flags_false_apagan_todos_los_respaldos():
    settings = _settings(
        groq_chat_fallback_enabled=False,
        gemini_chat_fallback_enabled=False,
        openrouter_chat_fallback_enabled=False,
        opencode_free_chat_fallback_enabled=False,
    )
    chat = create_chat_llm_provider(settings)
    assert getattr(chat, "backup", None) is None
    assert _openrouter_backup(settings, None) == ()


def test_openrouter_auto_con_clave_es_el_ultimo_respaldo():
    assert len(_openrouter_backup(_settings(), None)) == 1


# --- Ejecucion: Go primero, respaldo solo tras su fallo ---


def test_go_ok_no_llama_al_respaldo():
    go, groq = _Fake(_resp()), _Fake(_resp(provider="groq", model=GROQ_MODEL), name="groq")
    out = _run(_chat(go, groq).complete(REQ))
    assert out.provider == GO_SUBSCRIPTION_PROVIDER and groq.calls == 0
    assert fallback_notice(out) is None


def test_go_lento_dentro_de_su_plazo_gana_sin_carrera():
    go = _Fake(_resp(), delay=0.15)
    groq = _Fake(_resp(provider="groq", model=GROQ_MODEL), name="groq")
    out = _run(_chat(go, groq, delay=0.4).complete(REQ))
    assert out.provider == GO_SUBSCRIPTION_PROVIDER and groq.calls == 0


def test_go_falla_el_respaldo_responde_y_queda_etiquetado():
    go = _Fake(ProviderHTTPError("opencode-go", 500))
    groq = _Fake(_resp(provider="groq", model=GROQ_MODEL), name="groq")
    out = _run(_chat(go, groq).complete(REQ))
    assert out.provider == "groq" and groq.calls == 1
    assert out.fallback_trail[0].startswith(f"{GO_SUBSCRIPTION_PROVIDER}:")
    assert fallback_notice(out) == (
        "Respondido por respaldo (Groq) porque OpenCode Go falló: error del servidor (HTTP 500)."
    )


def test_go_agota_su_plazo_se_cancela_y_entra_el_respaldo():
    go = _Fake(_resp(), delay=5)
    groq = _Fake(_resp(provider="groq", model=GROQ_MODEL), name="groq")
    out = _run(_chat(go, groq, total=2, delay=0.05).complete(REQ))
    assert out.provider == "groq" and go.cancelled
    assert fallback_notice(out) == "Respondido por respaldo (Groq) porque OpenCode Go falló: no respondió a tiempo."


def test_429_de_go_se_explica_como_limite_de_uso():
    out = _run(_chat(
        _Fake(ProviderHTTPError("opencode-go", 429)),
        _Fake(_resp(provider="gemini", model="gemini-3.5-flash-lite"), name="gemini"),
    ).complete(REQ))
    assert fallback_notice(out) == (
        "Respondido por respaldo (Gemini) porque OpenCode Go falló: límite de uso alcanzado (HTTP 429)."
    )


def test_el_chat_muestra_el_aviso_de_respaldo_en_la_respuesta():
    provider = _chat(
        _Fake(ProviderHTTPError("opencode-go", 503)),
        _Fake(_resp(provider="groq", model=GROQ_MODEL), name="groq"),
    )
    result = _run(ChatSynthesisService(provider).synthesize_general(
        question="Cuéntame algo", baseline=ChatResponse(answer="", sources=[]),
    ))
    assert result.answer.startswith(
        "Respondido por respaldo (Groq) porque OpenCode Go falló: error del servidor (HTTP 503)."
    )
    assert result.llm_trace["provider"] == "groq"


def test_sin_respaldo_y_go_caido_el_chat_da_respuesta_degradada_en_espanol():
    go_only = _Fake(ProviderHTTPError("opencode-go", 500))
    result = _run(ChatSynthesisService(go_only).synthesize_general(  # pyright: ignore[reportArgumentType]
        question="Cuéntame algo", baseline=ChatResponse(answer="", sources=[]),
    ))
    assert result.answer
    assert "Respondido por respaldo" not in result.answer
    assert result.model != "deepseek-v4.1-flash"


# --- Debate de tesis: sin modelos free detras del Go del dueno ---


def test_debate_go_luego_free_sin_gemini():
    provider = create_free_interactive_provider(_settings(gemini_chat_fallback_enabled=False))
    assert isinstance(provider, FreeInteractiveProvider)
    models = [member.model_router.default_model for member in provider.members]
    assert models == ["deepseek-v4.1-flash", "deepseek-v4.1-flash-free"]


def test_debate_con_la_pata_free_apagada_usa_solo_el_modelo_go():
    provider = create_free_interactive_provider(_settings(
        gemini_chat_fallback_enabled=False,
        opencode_free_chat_fallback_enabled=False,
    ))
    assert isinstance(provider, FreeInteractiveProvider)
    models = [member.model_router.default_model for member in provider.members]
    assert models == ["deepseek-v4.1-flash"]


def test_debate_con_gemini_lo_anade_detras_del_go():
    provider = create_free_interactive_provider(_settings())
    assert isinstance(provider, FreeInteractiveProvider)
    names = [member.name for member in provider.members]
    assert names[0] == "opencode-go"
    assert "gemini" in names


def test_debate_con_clave_del_tenant_usa_su_proveedor():
    config = TenantLLMConfig(
        provider="opencode-go",
        base_url="https://opencode.ai/zen/go/v1",
        model="deepseek-v4.1-flash",
        api_key="clave-tenant",
    )
    with tenant_llm_config_scope(config):
        provider = create_free_interactive_provider(_settings(opencode_go_api_key=None))
    assert getattr(provider, "billing_scope", None) == "tenant"
