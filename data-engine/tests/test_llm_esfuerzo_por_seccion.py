"""Esfuerzo de razonamiento por seccion: una tabla, override por env, y el campo llega al proveedor."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from app.core.config import LLM_REASONING_EFFORT_DEFAULTS, Settings
from app.llm.adapters import OpenAICompatibleProvider
from app.llm.contracts import LLMRequest, LLMResponse, Message, Usage
from app.llm.reasoning_sections import chat_section_for
from app.schemas import ChatResponse
from app.services import thesis_debate_service, thesis_deep_narrative, thesis_news_narrative
from app.services.chat_synthesis_service import ChatSynthesisService


def _settings(**over) -> Settings:
    return Settings(_env_file=None, **over)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def settings(monkeypatch):
    """get_settings() de los servicios devuelve estos Settings (sin env del host)."""
    holder = {"value": _settings()}

    def use(**over):
        holder["value"] = _settings(**over)
        return holder["value"]

    for module in (
        "app.core.config",
        "app.services.thesis_deep_narrative",
        "app.services.thesis_news_narrative",
        "app.services.thesis_debate_service",
        "app.services.chat_synthesis_service",
        "app.llm.reasoning_sections",
    ):
        monkeypatch.setattr(f"{module}.get_settings", lambda: holder["value"], raising=False)
    return use


def _go() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key="sk-sintetica",
        base_url="https://opencode.ai/zen/go/v1",
        default_model="deepseek-v4.1-flash",
        provider_name="opencode-go",
        reasoning_effort="high",
        reasoning_effort_models={"deepseek-v4.1-flash"},
    )


def _sent_effort(request: LLMRequest) -> str | None:
    """El campo `reasoning_effort` tal y como sale en el JSON hacia OpenCode Go."""
    return _go()._build_payload(request, "deepseek-v4.1-flash").get("reasoning_effort")


# --- La tabla y su override por env ---


def test_tabla_por_defecto_low_salvo_el_analisis_de_cartera():
    s = _settings()
    assert s.reasoning_effort_for("chat_cartera") == "high"
    for section in LLM_REASONING_EFFORT_DEFAULTS:
        if section != "chat_cartera":
            assert s.reasoning_effort_for(section) == "low", section


def test_override_por_env_json_cambia_solo_esa_seccion(monkeypatch):
    monkeypatch.setenv("LLM_REASONING_EFFORT_BY_SECTION", json.dumps({"tesis_profunda": "high", "chat_consulta": "max"}))
    s = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.reasoning_effort_for("tesis_profunda") == "high"
    assert s.reasoning_effort_for("chat_consulta") == "max"
    assert s.reasoning_effort_for("traduccion_titular") == "low"


def test_override_vacio_no_envia_el_parametro_y_variable_vacia_no_rompe(monkeypatch):
    assert _settings(llm_reasoning_effort_by_section={"debate": ""}).reasoning_effort_for("debate") is None
    monkeypatch.setenv("LLM_REASONING_EFFORT_BY_SECTION", "")
    assert Settings(_env_file=None).reasoning_effort_for("debate") == "low"  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ('{"tesis": "high"}', "Seccion de razonamiento desconocida"),
        ('{"tesis_profunda": "medio"}', "Esfuerzo no valido"),
        ("no-es-json", "debe ser un JSON"),
    ],
)
def test_override_invalido_falla_al_arrancar_con_mensaje_en_espanol(monkeypatch, value, message):
    monkeypatch.setenv("LLM_REASONING_EFFORT_BY_SECTION", value)
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_seccion_desconocida_en_codigo_es_un_error():
    with pytest.raises(KeyError):
        _settings().reasoning_effort_for("seccion_inventada")


# --- Cerebro por intencion ---


@pytest.mark.parametrize(
    ("question", "section"),
    [
        ("¿Cómo está diversificada mi cartera?", "chat_cartera"),
        ("¿Qué riesgos de concentración tiene mi portfolio?", "chat_cartera"),
        ("¿Cuál es el PER de UBER?", "chat_consulta"),
        ("¿Cuánta caja tiene ASTS?", "chat_consulta"),
    ],
)
def test_cerebro_elige_seccion_por_intencion(question, section):
    assert chat_section_for(question) == section


class _Capture:
    name = "capture"
    supported_capabilities = frozenset({"text", "structured_output"})
    model_router = None

    def __init__(self, text: str):
        self.text = text
        self.requests: list[LLMRequest] = []

    async def complete(self, request):
        self.requests.append(request)
        return LLMResponse(Message("assistant", self.text), Usage(), "deepseek-v4.1-flash", "opencode-go", finish_reason="stop")


def _structured(question: str) -> LLMRequest:
    from tests.test_chat_synthesis_service import _baseline, _llm_payload

    provider = _Capture(json.dumps(_llm_payload()))
    asyncio.run(ChatSynthesisService(provider).synthesize(  # pyright: ignore[reportArgumentType]
        question=question, ticker="AAA", baseline=_baseline(), enable_debate=False,
    ))
    return provider.requests[0]


def test_cerebro_consulta_rapida_envia_low(settings):
    settings()
    assert _sent_effort(_structured("¿Cuál es el margen bruto?")) == "low"


def test_cerebro_analisis_de_cartera_envia_high(settings):
    settings()
    request = _structured("¿Cómo está diversificada mi cartera?")
    assert _sent_effort(request) == "high"
    # Con high el razonamiento usa hasta ~3,9k tokens: 1800 lo truncaba.
    assert request.max_tokens >= 4000


def test_cerebro_general_envia_su_seccion_y_respeta_el_override(settings):
    settings(llm_reasoning_effort_by_section={"chat_general": "max"})
    provider = _Capture("Respuesta breve en español.")
    asyncio.run(ChatSynthesisService(provider).synthesize_general(  # pyright: ignore[reportArgumentType]
        question="Cuéntame algo", baseline=ChatResponse(answer="", sources=[]),
    ))
    assert _sent_effort(provider.requests[0]) == "max"


# --- Tesis y debate ---

_FACTS = [{"id": 1, "texto": "Ingresos 2024: 436,2 M$", "fuente": "10-K 2024"}]


def test_tesis_profunda_envia_low_con_tope_que_deja_sitio_al_razonamiento(settings):
    settings()
    request = thesis_deep_narrative._build_request(_FACTS)
    assert _sent_effort(request) == "low"
    assert request.max_tokens >= 16000


def test_tesis_profunda_respeta_el_env_explicito_antiguo(settings):
    settings(thesis_deep_narrative_reasoning_effort="none")
    assert _sent_effort(thesis_deep_narrative._build_request(_FACTS)) == "none"


def test_tesis_noticias_sigue_la_tabla(settings):
    settings(llm_reasoning_effort_by_section={"tesis_noticias": "high"})
    request = thesis_news_narrative.build_request("UBER", [])
    assert _sent_effort(request) == "high"
    assert request.max_tokens >= 6000


def test_debate_envia_su_seccion(settings):
    settings(llm_reasoning_effort_by_section={"debate": "max"})
    provider = _Capture("Texto del debate en español, claro y suficiente para pasar.")
    asyncio.run(thesis_debate_service._complete_text(
        provider,  # pyright: ignore[reportArgumentType]
        system="s", user="u", task="red_team", max_tokens=2000, temperature=0.2,
    ))
    assert _sent_effort(provider.requests[0]) == "max"
