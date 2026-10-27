"""Ningun respaldo silencioso: todo va por el OpenCode Go del dueno salvo opt-in explicito."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.llm.chat_provider import _openrouter_backup, create_chat_llm_provider
from app.llm.free_interactive import FreeInteractiveProvider, create_free_interactive_provider
from app.llm.tenant_config import TenantLLMConfig, tenant_llm_config_scope


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


def test_con_todas_las_claves_y_auto_el_chat_solo_usa_opencode_go():
    chat = create_chat_llm_provider(_settings())
    assert chat.name == "opencode-go-subscription"
    assert getattr(chat, "backup", None) is None


def test_openrouter_no_entra_sin_su_flag_aunque_groq_este_encendido():
    settings = _settings(groq_chat_fallback_enabled=True)
    assert _openrouter_backup(settings, None) == ()
    on = _settings(groq_chat_fallback_enabled=True, openrouter_chat_fallback_enabled=True)
    assert len(_openrouter_backup(on, None)) == 1


def test_debate_usa_solo_el_modelo_go_sin_free_de_respaldo():
    provider = create_free_interactive_provider(_settings())
    assert isinstance(provider, FreeInteractiveProvider)
    models = [member.model_router.default_model for member in provider.members]
    assert models == ["deepseek-v4.1-flash"]


def test_debate_con_gemini_explicito_lo_anade_detras_del_go():
    provider = create_free_interactive_provider(_settings(gemini_chat_fallback_enabled=True))
    assert isinstance(provider, FreeInteractiveProvider)
    names = [member.name for member in provider.members]
    assert names[0] == "opencode-go"
    assert "gemini" in names


def test_debate_legacy_free_conserva_los_free_si_el_modelo_configurado_es_free():
    provider = create_free_interactive_provider(_settings(opencode_go_model="deepseek-v4.1-flash-free"))
    assert isinstance(provider, FreeInteractiveProvider)
    assert len(provider.members) > 1


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


@pytest.mark.parametrize("flag", ["groq_chat_fallback_enabled", "gemini_chat_fallback_enabled"])
def test_auto_es_apagado(flag):
    settings = _settings()
    assert getattr(settings, flag) is None
    assert settings.groq_chat_fallback_active is False
    assert settings.gemini_chat_fallback_active is False
