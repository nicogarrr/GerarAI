"""Chat de empresa: «Tu posición» y «Avisos abiertos» del propio usuario.

R1-02 (prueba real 2026-11-03): «¿Debería comprar más Uber?» contestaba
«falta tu posición actual» con 20 UBER en cartera. El contexto de la síntesis
(y el degradado) lleva ahora la posición y los RiskEvent abiertos del tenant
que pregunta, citables como position:<id> y risk_event:<id>. Nunca los de
otro tenant.
"""

import asyncio
import json

from sqlalchemy import select

from app.llm import LLMResponse, Message
from app.llm.contracts import Usage
from app.models.entities import Company, Position, RiskEvent
from app.schemas import ChatResponse, SynthesisSection
from app.services.chat_service import ChatService
from app.services.chat_synthesis_service import SECTION_ORDER, ChatSynthesisService
from tests.cerebro_seed import seeded_session


def _company(db, ticker):
    return db.scalars(select(Company).where(Company.ticker == ticker)).one()


def _uber_with_alert(db):
    uber = _company(db, "UBER")
    event = RiskEvent(
        tenant_id=1, company_id=uber.id, severity="warning", event_type="concentration",
        message="UBER pesa más del 10 % de la cartera", status="open",
    )
    closed = RiskEvent(
        tenant_id=1, company_id=uber.id, severity="warning", event_type="concentration",
        message="aviso cerrado antiguo", status="resolved",
    )
    db.add_all([event, closed])
    db.flush()
    return uber, event, closed


def _ask(db, tenant_id, ticker, question):
    db.info["tenant_id"] = tenant_id
    return ChatService()._deterministic_answer(db, question, "company", ticker)


def _types(response):
    return {source.get("type") for source in response.sources}


def test_owner_sees_position_and_open_alert_in_context_and_degraded_answer():
    db = seeded_session()
    uber, event, closed = _uber_with_alert(db)
    position = db.scalars(select(Position).where(Position.tenant_id == 1, Position.company_id == uber.id)).one()

    response = _ask(db, 1, "UBER", "¿Debería comprar más Uber?")

    facts = next(section for section in response.sections if section.key == "facts")
    assert f"position:{position.id}" in facts.citations
    assert f"risk_event:{event.id}" in facts.citations
    assert f"risk_event:{closed.id}" not in facts.citations
    assert "Tu posición en UBER: 20 acciones" in facts.body
    assert "12 % de tu cartera" in facts.body  # 1.200 de 10.000 EUR
    assert "valor 1.200,00 EUR" in facts.body
    assert "UBER pesa más del 10 %" in facts.body
    assert "aviso cerrado" not in facts.body
    assert {"position", "risk_event"} <= _types(response)
    # El degradado devuelve esta prosa tal cual: ya no puede decir que falta.
    assert "Tu posición en UBER: 20 acciones" in response.answer
    assert "Aviso abierto (warning): UBER pesa más del 10 %" in response.answer
    assert "[position:" not in response.answer


def test_other_tenant_never_sees_owner_position_or_alerts():
    db = seeded_session()
    _uber_with_alert(db)
    # Usuario B (tenant 2) pregunta por UBER, que solo tiene A.
    response = _ask(db, 2, "UBER", "¿Debería comprar más Uber?")
    dump = json.dumps(response.model_dump(), default=str, ensure_ascii=False)
    assert not {"position", "risk_event"} & _types(response)
    assert "Tu posición" not in dump
    assert "pesa más del 10" not in dump
    assert "position:" not in dump and "risk_event:" not in dump

    # Y A nunca ve la posición «SECRET» de B (9 acciones).
    response_a = _ask(db, 1, "SECRET", "¿Compro más SECRET?")
    dump_a = json.dumps(response_a.model_dump(), default=str, ensure_ascii=False)
    assert "Tu posición" not in dump_a
    assert "position" not in _types(response_a)

    # B sí ve la suya.
    response_b = _ask(db, 2, "SECRET", "¿Compro más SECRET?")
    assert "Tu posición en SECRET: 9 acciones" in response_b.answer


def test_no_tenant_means_no_holding_context():
    db = seeded_session()
    _uber_with_alert(db)
    db.info.pop("tenant_id", None)
    response = ChatService()._deterministic_answer(db, "¿Compro más Uber?", "company", "UBER")
    assert "Tu posición" not in response.answer
    assert not {"position", "risk_event"} & _types(response)


class _Provider:
    name = "stub"

    def __init__(self, payload=None, error=None):
        self.payload, self.error = payload, error

    async def complete(self, request):
        if self.error is not None:
            raise self.error
        return LLMResponse(
            message=Message("assistant", json.dumps(self.payload, ensure_ascii=False)),
            usage=Usage(input_tokens=100, output_tokens=50, total_tokens=150),
            model="stub-model", provider="stub", request_id="req-1",
        )


def _baseline():
    facts_cites = ["financial_fact:1", "position:7", "risk_event:3"]
    sections = [
        SynthesisSection(
            key=key,
            body=(
                "- Ingresos 100 [financial_fact:1]\n"
                "- Tu posición en UBER: 20 acciones, coste medio 65,00 USD, valor 1.200,00 EUR, "
                "12 % de tu cartera [position:7]\n"
                "- Aviso abierto (warning): UBER pesa más del 10 % de la cartera [risk_event:3]"
            ) if key == "facts" else f"baseline {key}",
            citations=facts_cites if key == "facts" else (["financial_fact:1"] if key == "calculations" else []),
        )
        for key in SECTION_ORDER
    ]
    sources = [
        {"type": "financial_fact", "id": 1, "title": "Ingresos"},
        {"type": "position", "id": 7, "title": "Tu posición en UBER",
         "text": "Tu posición en UBER: 20 acciones, coste medio 65,00 USD, valor 1.200,00 EUR, 12 % de tu cartera"},
        {"type": "risk_event", "id": 3, "title": "Aviso abierto UBER",
         "text": "Aviso abierto (warning): UBER pesa más del 10 % de la cartera"},
    ]
    return ChatResponse(answer="baseline", sections=sections, sources=sources)


def test_synthesis_may_cite_position_and_risk_event_and_use_their_figures():
    payload = {
        "sections": [
            {
                "key": key,
                "body": f"llm {key}",
                "citations": (
                    ["financial_fact:1", "position:7", "risk_event:3"] if key == "facts"
                    else ["financial_fact:1"] if key == "calculations"
                    else ["position:7", "risk_event:3"] if key == "conclusion"
                    else []
                ),
            }
            for key in SECTION_ORDER
        ],
        "confidence": 0.7,
        "insufficient_data": False,
        "answer": (
            "Ya tienes 20 acciones de UBER, que pesan un 12 % de tu cartera y superan el aviso "
            "del 10 %; antes de comprar más conviene revisar esa concentración."
        ),
    }
    result = asyncio.run(ChatSynthesisService(_Provider(payload=payload)).synthesize(
        question="¿Debería comprar más Uber?", ticker="UBER", baseline=_baseline(),
    ))
    assert result.model == "stub-model", result.llm_trace
    assert result.llm_trace["citation_verification"] is True
    assert "20 acciones" in result.answer


def test_degraded_synthesis_keeps_position_in_answer():
    baseline = _baseline()
    baseline.answer = "Datos de UBER.\n\nTu posición en UBER: 20 acciones"
    result = asyncio.run(ChatSynthesisService(_Provider(error=RuntimeError("caído"))).synthesize(
        question="¿Debería comprar más Uber?", ticker="UBER", baseline=baseline,
    ))
    assert result.llm_trace.get("fallback") is True
    assert "Tu posición en UBER: 20 acciones" in result.answer


def test_missing_average_cost_is_nd_instead_of_zero(monkeypatch):
    from app.services import chat_service

    for en in (False, True):
        db = seeded_session()
        db.info['tenant_id'] = 1
        uber = _company(db, 'UBER')
        pos = db.scalars(select(Position).where(Position.tenant_id == 1, Position.company_id == uber.id)).one()
        pos.average_cost = None
        monkeypatch.setattr(chat_service, '_english', lambda: en)
        with db.no_autoflush:
            _, lines, _ = ChatService()._holding_context(db, uber)
        line = lines[0]
        assert ('average cost N/D' if en else 'coste medio N/D') in line
        assert 'coste medio 0,00' not in line
        assert 'average cost 0.00' not in line
        db.close()
