"""Provider Go DEDICADO a narrativas de tesis: flag, validación y fail-closed.

Offline: ningún test toca la red ni Go; el MockTransport solo existiría si
algún test llamara a complete() (ninguno lo hace: se prueba construcción,
validación y wiring).
"""

import pytest

from app.core.config import Settings
from app.llm.adapters import DisabledProvider, OpenAICompatibleProvider
from app.llm.contracts import LLMRequest, Message
from app.llm.thesis_go import (
    THESIS_GO_ALLOWED_MODELS,
    THESIS_GO_ENDPOINT,
    create_thesis_narrative_provider,
)


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _request() -> LLMRequest:
    return LLMRequest(messages=[Message("user", "hola")])


def test_flag_disabled_devuelve_provider_global_previo() -> None:
    # Comportamiento anterior intacto: misma factoría global, misma config.
    provider = create_thesis_narrative_provider(
        _settings(thesis_go_enabled=False, opencode_go_api_key="k"))
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.name == "opencode-go"
    assert provider._base_url == "https://opencode.ai/zen/go/v1"  # noqa: SLF001


def test_flag_disabled_sin_key_global_da_disabled_global() -> None:
    provider = create_thesis_narrative_provider(
        _settings(thesis_go_enabled=False, opencode_go_api_key=None))
    assert isinstance(provider, DisabledProvider)
    assert provider.reason == "opencode_go_api_key_not_configured"


def test_enabled_valido_construye_dedicado_sin_fallback_ni_overrides() -> None:
    provider = create_thesis_narrative_provider(_settings(
        thesis_go_enabled=True,
        thesis_go_api_key="clave-tesis",
        thesis_go_base_url="https://opencode.ai/zen/go/v1/",  # barra final tolerada
        thesis_go_model="deepseek-v4.1-flash",
        # La config global puede tener overrides/fallback: el dedicado NO los hereda.
        llm_model_overrides={"x": "y"},
        opencode_go_fallback_model="deepseek-v4.1-flash-free",
    ))
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.name == "opencode-go"
    assert provider._base_url == THESIS_GO_ENDPOINT  # noqa: SLF001
    assert provider.model_router.resolve(_request()) == "deepseek-v4.1-flash"
    assert provider._fallback_model is None  # noqa: SLF001
    assert provider._strip_response_format is True  # noqa: SLF001 (fix #2181)


@pytest.mark.parametrize("kw,reason", [
    ({"thesis_go_api_key": None}, "thesis_go_api_key_not_configured"),
    ({"thesis_go_api_key": "k", "thesis_go_base_url": "http://bridge.local/v1"},
     "thesis_go_endpoint_not_approved"),
    ({"thesis_go_api_key": "k", "thesis_go_model": "gpt-5-mini"},
     "thesis_go_model_not_allowed"),
])
def test_enabled_config_invalida_disabled_nunca_bridge(kw, reason) -> None:
    provider = create_thesis_narrative_provider(_settings(
        thesis_go_enabled=True, opencode_go_api_key="clave-global", **kw))
    # Aunque la key GLOBAL exista y el bridge global funcionaría: disabled.
    assert isinstance(provider, DisabledProvider)
    assert provider.reason == reason


def test_allowlist_es_solo_el_flash_aprobado() -> None:
    assert frozenset({"deepseek-v4.1-flash"}) == THESIS_GO_ALLOWED_MODELS
