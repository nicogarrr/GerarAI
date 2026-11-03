"""La traza del degradado dice POR QUE cayo, no solo el tipo (prueba real 2026-11-03).

Con el Go de Nico una de cada ~7 respuestas caia al degradado determinista y
``llm_trace`` solo guardaba ``fallback_reason="ValueError"``: imposible saber
cual de las ~10 validaciones la habia tirado. Ahora guarda el mensaje, sin
secretos y acotado.
"""

import asyncio

from app.llm import LLMResponse, Message
from app.llm.contracts import Usage
from app.schemas import ChatResponse
from app.services.chat_synthesis_service import (
    FALLBACK_DETAIL_MAX,
    ChatSynthesisService,
    _fallback_detail,
    _general_text_rejection,
    _inferred_general_text_valid,
)
from tests.test_chat_synthesis_service import StubProvider, _baseline, _llm_payload


def test_structured_fallback_records_the_validation_message():
    provider = StubProvider(payload=_llm_payload(citations=["financial_fact:999"]))
    result = asyncio.run(ChatSynthesisService(provider).synthesize(
        question="q", ticker="AAA", baseline=_baseline()
    ))
    assert result.llm_trace["fallback_reason"] == "ValueError"
    assert "Unsupported citation" in result.llm_trace["fallback_detail"]


def test_provider_error_detail_never_carries_a_secret():
    provider = StubProvider(error=RuntimeError(
        "401 from upstream: api_key=abc123SECRETVALUE Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz"
    ))
    result = asyncio.run(ChatSynthesisService(provider).synthesize(
        question="q", ticker="AAA", baseline=_baseline()
    ))
    detail = result.llm_trace["fallback_detail"]
    assert "401 from upstream" in detail
    assert "abc123SECRETVALUE" not in detail
    assert "sk-abcdefghijklmnop" not in detail


def test_detail_is_bounded_and_single_line():
    detail = _fallback_detail(ValueError("x\n" * 500))
    assert len(detail) <= FALLBACK_DETAIL_MAX
    assert "\n" not in detail


def test_ungrounded_number_message_names_the_figures():
    detail = _fallback_detail(ValueError("Ungrounded number in model answer: 51.200"))
    assert "51.200" in detail


def test_general_fallback_keeps_the_detail():
    baseline = ChatResponse(answer="base", sources=[], proposed_actions=[])
    out = ChatSynthesisService._general_fallback(
        baseline, reason="provider_or_guard_failure", detail="ValueError: Ungrounded general output"
    )
    assert out.llm_trace["fallback_detail"] == "ValueError: Ungrounded general output"
    assert out.llm_trace["reason"] == "provider_or_guard_failure"


def test_general_rejection_names_the_rule_and_the_figure():
    assert _general_text_rejection("El PER compara el precio con el beneficio.") is None
    assert _general_text_rejection("El PER de esa empresa es 20.") == "cifra exacta sin aproximador: 20"
    assert _general_text_rejection("Según el informe anual, va bien.") == "atribución a una fuente oficial no dada"
    # El booleano de siempre no cambia.
    assert _inferred_general_text_valid("El PER de esa empresa es 20.") is False
    assert _inferred_general_text_valid("El PER compara el precio con el beneficio.") is True


class _TextProvider:
    name = "stub"

    def __init__(self, text: str):
        self.text = text

    async def complete(self, request):
        return LLMResponse(
            message=Message("assistant", self.text),
            usage=Usage(input_tokens=10, output_tokens=10, total_tokens=20),
            model="stub-model",
            provider="stub",
            request_id="req-g",
        )


def test_general_path_fallback_says_which_rule_rejected_it():
    baseline = ChatResponse(answer="base", sources=[], proposed_actions=[])
    out = asyncio.run(ChatSynthesisService(_TextProvider("Según el informe anual, el PER sube.")).synthesize_general(
        question="¿Cómo piensas sobre invertir a largo plazo?", baseline=baseline,
    ))
    assert out.llm_trace["fallback"] is True
    assert out.llm_trace["fallback_detail"].endswith("atribución a una fuente oficial no dada")
