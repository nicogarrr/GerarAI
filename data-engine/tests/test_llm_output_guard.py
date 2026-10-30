import asyncio

import pytest

from app.llm import LLMRequest, LLMResponse, Message, Usage
from app.services import llm_output_guard as g

CLEAN = (
    "La compania mantiene un margen operativo estable y el flujo de caja libre "
    "cubre el dividendo. El EBITDA y el ROIC apuntan a una valoracion razonable."
)


def _resp(text):
    return LLMResponse(message=Message("assistant", text), usage=Usage(1, 1), model="m", provider="p")


class Fake:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = []

    async def complete(self, request):
        self.calls.append(request)
        return _resp(self.texts.pop(0))


def _req():
    return LLMRequest(messages=[Message("system", "s"), Message("user", "u")])


@pytest.fixture(autouse=True)
def _reset():
    g.reset_guard_stats()


def test_clean_text_passes_untouched():
    assert g.inspect_text(CLEAN) == []
    p = Fake(CLEAN)
    out = asyncio.run(g.complete_guarded(p, _req(), source="t"))
    assert out.response.text == CLEAN and not out.retried and len(p.calls) == 1
    assert g.guard_stats()["t.calls"] == 1 and "t.triggered" not in g.guard_stats()


def test_quoted_english_and_financial_terms_are_ignored():
    text = 'El CEO dijo "the company will grow" y el free cash flow, el P/E y el EBITDA mejoran.'
    assert g.inspect_text(text) == []


def test_cjk_detected():
    assert g.REASON_CJK in g.inspect_text("La empresa tiene una buena 문화 interna.")
    assert g.REASON_CJK in g.inspect_text("margen 利润 estable")


def test_mixed_english_detected():
    text = "Therefore the margin is stable, which is provided that the demand will hold."
    assert g.REASON_ENGLISH in g.inspect_text(text)


def test_corrupt_tokens_detected():
    assert g.REASON_CORRUPT in g.inspect_text("La valoracion es múltijodepends de otros factores.")
    assert g.REASON_CORRUPT in g.inspect_text("Los se-components? del indice suben.")
    assert g.REASON_CORRUPT in g.inspect_text("Texto con \ufffd roto")


def test_json_keys_do_not_count_only_values():
    assert (
        g.inspect_response_text('{"summary": "Margen estable y caja neta.", "insufficient_data": false}')
        == []
    )
    assert g.REASON_CJK in g.inspect_response_text('{"summary": "Margen 문화 estable"}')


def test_cjk_triggers_one_retry_then_recovers():
    p = Fake("Margen estable 문화.", CLEAN)
    out = asyncio.run(g.complete_guarded(p, _req(), source="t"))
    assert out.retried and out.response.text == CLEAN and len(out.discarded) == 1
    assert len(p.calls) == 2
    assert "REINTENTO" in p.calls[1].messages[0].content
    s = g.guard_stats()
    assert s["t.triggered"] == 1 and s["t.recovered"] == 1 and s["t.reason.cjk"] == 1


def test_mixed_english_triggers_retry():
    bad = "However the company is strong, which is because the demand will grow and the margin is high."
    p = Fake(bad, CLEAN)
    out = asyncio.run(g.complete_guarded(p, _req(), source="t"))
    assert out.retried and len(p.calls) == 2


def test_failed_retry_raises_and_counts_rejection():
    p = Fake("Margen 문화.", "Otra vez 문화.")
    with pytest.raises(g.LLMOutputRejected) as exc:
        asyncio.run(g.complete_guarded(p, _req(), source="t"))
    assert exc.value.reasons == [g.REASON_CJK] and len(p.calls) == 2
    assert g.guard_stats()["t.rejected"] == 1


def test_english_off_ignores_english_but_not_cjk():
    text = "However the company is strong, which is because the demand will grow and the margin is high."
    assert g.inspect_text(text, english="off") == []
    assert g.REASON_CJK in g.inspect_text(text + " 문화", english="off")


def test_thesis_debate_degrades_when_guard_rejects(monkeypatch):
    from app.services import thesis_debate_service as svc

    p = Fake(*(["Texto 문화 roto."] * 2))
    with pytest.raises(g.LLMOutputRejected):
        asyncio.run(
            svc._complete_text(p, system="s", user="u", task="red_team", max_tokens=10, temperature=0.1)
        )


# --- regresiones de auditoria: deteccion agregada y contabilidad de presupuesto ---
import json as _json
from types import SimpleNamespace
from unittest.mock import MagicMock


def test_json_english_values_are_aggregated():
    payload = _json.dumps(
        {
            "sections": [
                {"key": "facts", "body": "The margin is stable."},
                {"key": "x", "body": "The debt is high."},
            ]
        }
    )
    assert g.REASON_ENGLISH in g.inspect_response_text(payload)


def test_single_short_english_sentence_is_detected_but_spanish_is_not():
    assert g.REASON_ENGLISH in g.inspect_text("The company is profitable.")
    assert g.inspect_text("La compania es rentable y tiene caja neta.") == []
    assert g.inspect_text("Tu has visto que el margen mejora.") == []


def test_ids_and_enums_in_json_are_not_prose():
    payload = _json.dumps(
        {"sections": [{"key": "facts", "citations": ["financial_fact:1"], "body": "Margen estable."}]}
    )
    assert g.inspect_response_text(payload) == []


def test_long_legitimate_spanish_word_is_not_corrupt():
    assert g.inspect_text("Es anticonstitucionalmente dudoso.") == []


class _Budget:
    records: list = []
    allow = True

    def can_spend(self, db, cost):
        return type(self).allow

    def record(self, db, model, workflow, cost, tokens):
        type(self).records.append((workflow, tokens))

    @staticmethod
    def estimate_cost_eur(model, i, o):
        return 0.001


@pytest.fixture
def budget(monkeypatch):
    _Budget.records = []
    _Budget.allow = True
    return _Budget


def _chat_payload(body, answer=None):
    from app.services.chat_synthesis_service import SECTION_ORDER

    # El contrato de sintesis exige `answer`: la prosa natural visible. Sin
    # answer explicita, el fixture reutiliza el body (prosa corta valida en
    # los candidatos en castellano; en los ingleses el guard de idioma salta
    # antes, igual que con las secciones).
    return {
        "sections": [
            {
                "key": k,
                "body": body,
                "citations": ["financial_fact:1"] if k in ("facts", "calculations") else [],
            }
            for k in SECTION_ORDER
        ],
        "confidence": 0.8,
        "insufficient_data": False,
        "answer": body if answer is None else answer,
    }


class _JsonProvider:
    name = "stub"

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return LLMResponse(
            message=Message("assistant", _json.dumps(self.payloads.pop(0))),
            usage=Usage(100, 50, 150),
            model="stub-model",
            provider="stub",
        )


def _run_chat(provider):
    from app.schemas import ChatResponse, SynthesisSection
    from app.services.chat_synthesis_service import SECTION_ORDER, ChatSynthesisService

    sections = [
        SynthesisSection(
            key=k,
            body=f"baseline {k}",
            citations=["financial_fact:1"] if k in ("facts", "calculations") else [],
        )
        for k in SECTION_ORDER
    ]
    baseline = ChatResponse(answer="b", sections=sections, sources=[{"type": "financial_fact", "id": 1}])
    return asyncio.run(
        ChatSynthesisService(provider).synthesize(
            question="q", ticker="AAA", baseline=baseline, db=MagicMock()
        )
    )


def test_chat_synthesis_english_sections_retry_and_record_both_calls(monkeypatch, budget):
    monkeypatch.setattr("app.services.chat_synthesis_service.BudgetController", lambda: budget())
    provider = _JsonProvider(
        _chat_payload("The margin is stable and the debt is low."),
        _chat_payload("Margen estable y deuda baja."),
    )
    result = _run_chat(provider)
    assert provider.calls == 2 and len(budget.records) == 2
    # La respuesta visible es la prosa natural, nunca la seccion cruda.
    assert result.model == "stub-model"
    assert result.answer == "Margen estable y deuda baja."
    assert "HECHO" not in result.answer


def test_chat_synthesis_double_rejection_falls_back_and_records_both(monkeypatch, budget):
    monkeypatch.setattr("app.services.chat_synthesis_service.BudgetController", lambda: budget())
    bad = _chat_payload("The margin is stable and the debt is low.")
    provider = _JsonProvider(bad, bad)
    result = _run_chat(provider)
    assert provider.calls == 2 and len(budget.records) == 2
    assert result.model == "deterministic"


def test_chat_synthesis_retry_is_skipped_when_budget_is_gone(monkeypatch, budget):
    class Tight(budget):
        calls = 0

        def can_spend(self, db, cost):
            type(self).calls += 1
            return type(self).calls == 1  # solo el primer intento cabe

    monkeypatch.setattr("app.services.chat_synthesis_service.BudgetController", lambda: Tight())
    provider = _JsonProvider(_chat_payload("The margin is stable and the debt is low."))
    result = _run_chat(provider)
    assert provider.calls == 1 and len(budget.records) == 1
    assert result.model == "deterministic"


def _narrative(provider, monkeypatch, budget):
    from app.services import research_assistant_narrative as n

    monkeypatch.setattr(n, "BudgetController", lambda: budget())
    baseline = {
        "status": "answered",
        "citations": [
            {
                "id": "financial_fact:1",
                "kind": "financial_fact",
                "excerpt": "Caja neta 10",
                "as_of": "2026-01-01",
            }
        ],
    }
    payload = SimpleNamespace(question="q", mode="m")
    return asyncio.run(n.synthesize(MagicMock(), payload, baseline, provider=provider))


def test_narrative_records_discarded_and_final_response(monkeypatch, budget):
    class P:
        name = "stub"

        def __init__(self):
            self.texts = [
                _json.dumps(
                    {"sentences": [{"body": "Caja neta 10 文化", "citation_ids": ["financial_fact:1"]}]}
                ),
                _json.dumps({"sentences": [{"body": "Caja neta 10", "citation_ids": ["financial_fact:1"]}]}),
            ]
            self.calls = 0

        async def complete(self, request):
            self.calls += 1
            return LLMResponse(Message("assistant", self.texts.pop(0)), Usage(200, 0, 200), "m", "p")

    provider = P()
    out = _narrative(provider, monkeypatch, budget)
    assert provider.calls == 2 and len(budget.records) == 2
    assert "Caja neta 10" in out["answer"]


def test_narrative_double_rejection_records_both_and_returns_baseline(monkeypatch, budget):
    class P:
        name = "stub"
        calls = 0

        async def complete(self, request):
            type(self).calls += 1
            body = _json.dumps({"sentences": [{"body": "文化", "citation_ids": ["financial_fact:1"]}]})
            return LLMResponse(Message("assistant", body), Usage(200, 0, 200), "m", "p")

    out = _narrative(P(), monkeypatch, budget)
    assert P.calls == 2 and len(budget.records) == 2
    assert out["status"] == "answered" and "answer" not in out


def test_debate_llm_calls_counts_retry_and_double_rejection():
    from app.services.thesis_debate_service import debate_thesis

    class P:
        name = "stub"

        def __init__(self, script):
            self.script = list(script)
            self.calls = 0

        async def complete(self, request):
            self.calls += 1
            return LLMResponse(Message("assistant", self.script.pop(0)), Usage(1, 1, 2), "m", "p")

    ok = P(
        [
            "Texto 文化 roto.",
            "Caso alcista limpio.",
            "Caso bajista limpio.",
            "VEREDICTO: neutral | Equilibrado.",
        ]
    )
    res = asyncio.run(debate_thesis("SAN", "t", provider=ok))
    assert res["llm_calls"] == ok.calls == 4 and res["degraded"] is False
    bad = P(["文化 a", "文化 b", "Caso bajista limpio.", "VEREDICTO: neutral | Equilibrado."])
    res = asyncio.run(debate_thesis("SAN", "t", provider=bad))
    assert res["llm_calls"] == bad.calls == 4 and res["degraded"] is True


def test_cjk_rejection_uses_provider_cjk_retry_hook():
    """Chat 94,6 s: tras el primer rechazo CJK el reintento salta a la via
    rapida del proveedor (cadena Groq) en vez de repetir el primario lento."""

    class WithCjkRetry(Fake):
        def __init__(self, *texts):
            super().__init__(*texts)
            self.cjk_retry_calls = []

        async def complete_cjk_retry(self, request):
            self.cjk_retry_calls.append(request)
            return _resp(CLEAN)

    p = WithCjkRetry("Margen estable 문화.")
    out = asyncio.run(g.complete_guarded(p, _req(), source="t"))
    assert out.retried and out.response.text == CLEAN
    assert len(p.calls) == 1, "el primario lento no se repite"
    assert len(p.cjk_retry_calls) == 1
    assert "REINTENTO" in p.cjk_retry_calls[0].messages[0].content
    s = g.guard_stats()
    assert s["t.cjk_backup_retry"] == 1 and s["t.recovered"] == 1


def test_cjk_retry_hook_failure_propagates_rejection():
    class WithCjkRetry(Fake):
        async def complete_cjk_retry(self, request):
            return _resp("Otra vez 문화.")

    p = WithCjkRetry("Margen 문화.")
    with pytest.raises(g.LLMOutputRejected):
        asyncio.run(g.complete_guarded(p, _req(), source="t"))
    assert len(p.calls) == 1
    assert g.guard_stats()["t.rejected"] == 1


def test_english_rejection_does_not_use_cjk_hook():
    """El salto a Groq es especifico del rechazo CJK; el ingles reintenta en
    el mismo proveedor con el idioma forzado."""
    bad = "However the company is strong, which is because the demand will grow and the margin is high."

    class WithCjkRetry(Fake):
        async def complete_cjk_retry(self, request):
            raise AssertionError("no debe llamarse para rechazos no CJK")

    p = WithCjkRetry(bad, CLEAN)
    out = asyncio.run(g.complete_guarded(p, _req(), source="t"))
    assert out.retried and len(p.calls) == 2
    assert "t.cjk_backup_retry" not in g.guard_stats()


def test_rejected_cached_response_is_awaited_and_evicted():
    from types import SimpleNamespace
    seen = []
    class Provider:
        async def evict_cached(self, response):
            seen.append(response.cache_key)
    asyncio.run(g._evict(Provider(), SimpleNamespace(cache_key='rejected')))
    assert seen == ['rejected']


def test_cache_eviction_failure_is_nonfatal():
    from types import SimpleNamespace
    class Provider:
        async def evict_cached(self, response):
            raise RuntimeError('cache unavailable')
    asyncio.run(g._evict(Provider(), SimpleNamespace(cache_key='rejected')))
    asyncio.run(g._evict(object(), SimpleNamespace(cache_key='rejected')))
