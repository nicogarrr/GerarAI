"""cerebro-det: «proveedor caído» responde sin modelo y con 0 cifras inventadas.

Benchmark Cerebro 2026-11-08 (pasada 2, clave de OpenCode Go en HTTP 402):
11 preguntas sin ticker acabaron en «No puedo responderte con fuentes ahora
mismo; prueba de nuevo…», que no dice qué falta. Ahora, cuando el modelo no
está disponible (402, 429, plazo agotado o caída) o su redacción no pasa el
control de fuentes, la respuesta es determinista: los datos de la app tal
cual, más «N/D: falta X (motivo)». El texto añadido no lleva cifras, así que
toda cifra de la respuesta sale del baseline (0 cifras inventadas).
Sin llamadas reales a modelos: proveedores simulados.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from app.core.i18n import _request_language, set_language_scope
from app.llm.errors import ProviderHTTPError, ProviderResponseError, ProviderTransportError
from app.schemas import ChatResponse
from app.services.chat_synthesis_service import (
    ChatSynthesisService,
    _model_down_kind,
    _ungrounded_figures,
)

_BASE_ANSWER = "POOL cotiza a 211,70 USD (cierre del 6 nov 2026). Ingresos 5.311 millones USD (ejercicio 2025, filing)."
_PRICE = {"type": "price", "id": 1, "title": "Precio POOL", "url": "/research/POOL"}
_DOCTRINE = {"type": "knowledge_chunk", "id": 7, "title": "Carta 2024", "author": "Numantia", "text": "Compramos en 2024."}


def _baseline(sources, answer=_BASE_ANSWER) -> ChatResponse:
    return ChatResponse(
        answer=answer, sources=sources, proposed_actions=[], model="deterministic",
        prompt_version="t", confidence=0.5, llm_trace={},
    )


def _chained(outer: BaseException, cause: BaseException) -> BaseException:
    outer.__cause__ = cause
    return outer


def _http(status: int) -> ProviderHTTPError:
    return ProviderHTTPError("opencode-go", status)


_FAILURES = {
    "402_go": (_http(402), "limit"),
    "429_cadena": (
        _chained(
            ProviderResponseError("backup chain exhausted after primary opencode-go:m:ProviderHTTPError402"),
            ProviderHTTPError("opencode-free", 429),
        ),
        "limit",
    ),
    "go_enfriando": (
        _chained(ProviderHTTPError("gemini", 503), ProviderResponseError("opencode-go:m:cooling")),
        "limit",
    ),
    "plazo": (ProviderTransportError("opencode-go", "timeout", 1), "timeout"),
    "rechazo_guard": (
        _chained(
            ProviderResponseError("backup chain exhausted after primary opencode-go:m:ProviderResponseError"),
            ProviderHTTPError("opencode-free", 429),
        ),
        "rejected",
    ),
    "caida": (RuntimeError("connection reset"), "down"),
}


@pytest.mark.parametrize("name", sorted(_FAILURES))
def test_clase_del_fallo_es_determinista(name):
    exc, expected = _FAILURES[name]
    assert _model_down_kind(exc, "provider_or_guard_failure") == expected


class _Down:
    """Proveedor simulado que siempre falla: nada sale a la red."""

    name = "opencode-go"
    model_router = None

    def __init__(self, exc: BaseException):
        self.exc = exc
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        raise self.exc


def _ask(provider, baseline, question="¿Qué tal está el mercado?"):
    return asyncio.run(ChatSynthesisService(provider).synthesize_general(question=question, baseline=baseline))


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d[\d.,]*\d|\d", text)


@pytest.mark.parametrize("name", sorted(_FAILURES))
def test_proveedor_caido_con_datos_responde_con_los_datos_de_la_app(name):
    exc, _ = _FAILURES[name]
    provider = _Down(exc)
    out = _ask(provider, _baseline([_PRICE, _DOCTRINE]))

    assert provider.calls >= 1
    assert out.answer.startswith(_BASE_ANSWER)
    assert "N/D: falta" in out.answer and "(motivo:" in out.answer
    assert "No puedo responderte con fuentes" not in out.answer
    assert "prueba de nuevo" not in out.answer
    assert out.model == "deterministic"
    # La doctrina no es un dato de la app: no viaja como fuente del degradado.
    assert out.sources == [_PRICE]
    # 0 cifras inventadas: cada cifra de la respuesta está en el baseline.
    assert _ungrounded_figures(out.answer, [_BASE_ANSWER]) == []
    assert set(_numbers(out.answer)) <= set(_numbers(_BASE_ANSWER))


@pytest.mark.parametrize("name", sorted(_FAILURES))
def test_proveedor_caido_sin_datos_dice_que_falta_y_no_da_cifras(name):
    exc, _ = _FAILURES[name]
    out = _ask(_Down(exc), _baseline([], answer=""))

    assert "No puedo responderte con fuentes" not in out.answer
    assert "prueba de nuevo" not in out.answer
    assert out.answer.startswith("Te digo solo lo que tiene fuente. N/D: falta ")
    assert _numbers(out.answer) == []
    assert out.sources == []
    assert out.llm_trace["fallback"] is True and out.llm_trace["deterministic"] is True


def test_402_dice_saldo_o_limite_y_no_el_codigo():
    out = _ask(_Down(_http(402)), _baseline([], answer=""))
    assert "la redacción del modelo (motivo: el proveedor del modelo no tiene saldo o ha llegado a su límite de uso)" in out.answer
    assert out.llm_trace["model_down"] == "limit"
    assert "402" not in out.answer


def test_solo_doctrina_no_cuenta_como_datos_de_la_app():
    out = _ask(_Down(_http(429)), _baseline([_DOCTRINE], answer="Fragmento de 2024."))
    assert out.answer.startswith("Te digo solo lo que tiene fuente.")
    assert _numbers(out.answer) == []


def test_rechazo_del_guard_no_repite_las_cifras_del_candidato():
    out = ChatSynthesisService._general_fallback(
        _baseline([_PRICE]), reason="ungrounded",
        guard_reason="cifra con decimales no aproximada: 12,34",
    )
    assert "12,34" not in out.answer
    assert "N/D: falta la fuente de las cifras exactas" in out.answer
    assert _ungrounded_figures(out.answer, [_BASE_ANSWER]) == []


def test_rechazo_del_guard_dentro_de_la_excepcion_tambien_se_lee():
    exc = _chained(
        ProviderResponseError("Candidate rejected: Ungrounded general output: afirmación sobre la cartera del usuario"),
        ValueError("Ungrounded general output: afirmación sobre la cartera del usuario"),
    )
    out = ChatSynthesisService._general_fallback(_baseline([]), reason="provider_or_guard_failure", exc=exc)
    assert "N/D: falta tus posiciones guardadas" in out.answer


def test_tope_de_gasto_responde_con_datos_sin_llamar_al_modelo():
    out = ChatSynthesisService._general_fallback(_baseline([_PRICE]), reason="budget_exhausted")
    assert out.answer.startswith(_BASE_ANSWER)
    assert "tope de gasto en modelos de la app" in out.answer


def test_en_ingles_el_mismo_contrato(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    token = set_language_scope("en")
    try:
        with_data = ChatSynthesisService._general_fallback(_baseline([_PRICE]), reason="quota")
        empty = ChatSynthesisService._general_fallback(_baseline([], answer=""), reason="error", exc=_http(402))
    finally:
        _request_language.reset(token)
        get_settings.cache_clear()
    assert with_data.answer.startswith(_BASE_ANSWER)
    assert "N/D: missing the model's write-up (reason: the model provider is out of credit" in with_data.answer
    assert empty.answer.startswith("I'll only tell you what has a source. N/D: missing ")
    assert "can't answer with sources" not in empty.answer
    assert _numbers(empty.answer) == []
