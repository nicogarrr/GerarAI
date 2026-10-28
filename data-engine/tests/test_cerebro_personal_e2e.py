"""E2E del Cerebro con tus datos: enrutado de intenciones + contexto + anclaje.

Base sembrada con tus tickers reales (``tests/cerebro_seed.py``) y un LLM de
prueba que guarda lo que recibe: así se comprueba QUÉ datos llegan al modelo
(cartera, watchlist con DCA y margen, tesis, avisos, plan) y que la ruta es la
personal, no la abstención «Selecciona la empresa» ni el LLM sin contexto.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.llm import LLMResponse, Message, Usage
from app.services import user_context
from app.services.chat_service import ChatService
from app.services.personal_answer import (
    detect_personal_intent,
    ungrounded_numbers,
    ungrounded_tickers,
)
from tests.cerebro_seed import PORTFOLIO, WATCHLIST, fake_dca_reader, seeded_session


class EchoProvider:
    """LLM de prueba: guarda la petición y contesta con un texto fijo o con eco."""

    name = "echo"

    def __init__(self, reply: str | None = None):
        self.reply = reply
        self.requests: list = []

    @property
    def user_data(self) -> str:
        payload = json.loads(self.requests[-1].messages[-1].content)
        return payload["user_data"]

    async def complete(self, request):
        self.requests.append(request)
        payload = json.loads(request.messages[-1].content)
        # Eco: la primera línea con datos de la watchlist, copiada tal cual.
        text = self.reply
        if text is None:
            line = next(
                (ln for ln in payload["user_data"].splitlines() if ln.startswith("- POOL")),
                payload["user_data"].splitlines()[1],
            )
            text = f"Según tu watchlist: {line.removeprefix('- ')}"
        return LLMResponse(
            message=Message("assistant", text),
            usage=Usage(input_tokens=100, output_tokens=40, total_tokens=140),
            model="echo-model",
            provider="echo",
            request_id="r1",
        )


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(user_context, "default_dca_reader", fake_dca_reader)
    session = seeded_session()
    yield session
    session.close()


def _ask(db, question, provider=None, history=None):
    service = ChatService(provider=provider or EchoProvider())
    return asyncio.run(service.answer(db, question, "portfolio", None, history=history))


# ------------------------------------------------------------ intenciones


@pytest.mark.parametrize(
    "question,kind",
    [
        ("¿qué está barato de mi watchlist?", "barato"),
        ("¿Qué debo comprar hoy?", "barato"),
        ("¿Qué comprar hoy con mi aportación?", "barato"),
        ("¿Qué está barato?", "barato"),
        ("¿dónde meto la aportación de este mes?", "barato"),
        ("¿qué tengo en 4X?", "barato"),
        ("enséñame mi watchlist", "watchlist"),
        ("¿qué riesgo tengo?", "riesgo"),
        ("¿estoy muy concentrado?", "riesgo"),
        ("¿cómo va mi cartera?", "cartera"),
        ("¿cuánto aporto al mes?", "plan"),
        ("¿cuándo se invalidan mis tesis?", "tesis"),
        ("dame mi resumen fiscal", "fiscal"),
        ("¿qué sabes de mí?", "general"),
    ],
)
def test_intenciones_personales(question, kind):
    intent = detect_personal_intent(question)
    assert intent is not None and intent.kind == kind


@pytest.mark.parametrize(
    "question",
    ["¿Qué es el riesgo sistémico?", "Vende mi cartera", "hola", "¿qué es el margen de seguridad?", "precio de ASTS"],
)
def test_no_personales_siguen_su_ruta(question):
    assert detect_personal_intent(question) is None


# ------------------------------------------------------------ e2e


def test_barato_de_mi_watchlist_llega_con_toda_la_watchlist(db):
    provider = EchoProvider()
    resp = _ask(db, "¿qué está barato de mi watchlist?", provider)
    assert resp.llm_trace["path"] == "personal_context"
    assert resp.llm_trace["intent"] == "barato"
    data = provider.user_data
    for ticker in WATCHLIST:
        assert f"- {ticker}" in data
    assert "margen de seguridad +25,0 %, nivel DCA 4X DCA" in data  # POOL
    assert "nivel DCA RECORTE LIGERO" in data  # AAPL
    assert "## Cartera (/portfolio)" in data
    assert "se invalida si:" in data
    # El eco copia una línea del contexto: pasa el anclaje y se muestra tal cual.
    assert resp.llm_trace["grounding"] == "ok"
    assert "POOL" in resp.answer and "+25,0 %" in resp.answer
    assert "no tengo acceso" not in resp.answer.lower()
    assert {s["type"] for s in resp.sources} >= {"watch_item", "position"}


def test_riesgo_usa_cartera_tesis_y_avisos(db):
    provider = EchoProvider(reply="Tu mayor riesgo es la concentración: ASTS pesa 40,0 % (cartera).")
    resp = _ask(db, "¿qué riesgo tengo?", provider)
    assert resp.llm_trace["intent"] == "riesgo"
    data = provider.user_data
    for ticker in PORTFOLIO:
        assert f"- {ticker} (" in data
    assert "ONDS cae un 12 % en una sesión" in data
    assert "Retraso de más de 12 meses" in data  # criterio de invalidación de ASTS
    assert resp.answer.startswith("Tu mayor riesgo")
    assert "salud" not in resp.answer


def test_cifra_inventada_no_se_muestra(db):
    provider = EchoProvider(reply="POOL tiene un margen de seguridad del 41,5 % y es tu mejor compra.")
    resp = _ask(db, "¿qué está barato de mi watchlist?", provider)
    assert resp.llm_trace["fallback_reason"] == "ungrounded"
    assert 41.5 in resp.llm_trace["ungrounded_numbers"]
    assert "41,5" not in resp.answer
    # Respuesta determinista: POOL y KKR con +25,0 %; AAPL caro; IBRX y CPT sin valor justo.
    assert "- POOL: +25,0 % (4X DCA)." in resp.answer
    assert "- KKR: +25,0 % (2X DCA)." in resp.answer
    assert "AAPL -30,0 % (zona de recorte)" in resp.answer
    assert "UNH (3X DCA)" in resp.answer
    assert "IBRX" in resp.answer and "CPT" in resp.answer
    assert "ASTS (recorte fuerte)" in resp.answer


def test_ticker_inventado_no_se_muestra(db):
    provider = EchoProvider(reply="Lo más barato es TSLA, con margen de seguridad +25,0 %.")
    resp = _ask(db, "¿qué está barato?", provider)
    assert resp.llm_trace["fallback_reason"] == "ungrounded"
    assert resp.llm_trace["ungrounded_tickers"] == ["TSLA"]
    assert "TSLA" not in resp.answer


def test_llm_caido_responde_con_datos(db):
    class Down(EchoProvider):
        async def complete(self, request):
            raise RuntimeError("proveedor caído")

    resp = _ask(db, "¿qué riesgo tengo?", Down())
    assert resp.model == "deterministic"
    assert resp.llm_trace["fallback_reason"] == "provider_or_guard_failure"
    # ASTS 40 %; las 3 mayores 40 + 25 + 15 = 80 %.
    assert "ASTS pesa 40,0 % y las 3 mayores suman 80,0 %" in resp.answer
    assert "UBER -7,7 %" in resp.answer and "ONDS -33,3 %" in resp.answer
    assert "Tu tesis de ASTS se invalida si: Retraso de más de 12 meses" in resp.answer
    assert "ONDS cae un 12 %" in resp.answer


def test_cartera_con_posiciones_sigue_el_resumen_determinista(db):
    provider = EchoProvider()
    resp = _ask(db, "¿cómo va mi cartera?", provider)
    assert resp.prompt_version == "portfolio-overview-v1"
    assert provider.requests == []
    assert "Selecciona la empresa" not in resp.answer


def test_cartera_vacia_ya_no_da_selecciona_la_empresa(db):
    from app.models import Position

    db.query(Position).filter(Position.tenant_id == 1).delete()
    db.commit()
    resp = _ask(db, "¿cómo va mi cartera?", EchoProvider(reply="No tienes posiciones guardadas en la cartera."))
    assert resp.llm_trace["path"] == "personal_context"
    assert "Selecciona la empresa" not in resp.answer
    assert "posiciones" in resp.answer


def test_fiscal_solo_si_se_pide_y_sin_watchlist(db):
    provider = EchoProvider(reply="Tu resumen fiscal está en la página de impuestos.")
    resp = _ask(db, "dame mi resumen fiscal", provider)
    assert resp.llm_trace["intent"] == "fiscal"
    assert "## Resumen fiscal (/taxes)" in provider.user_data
    assert "## Watchlist" not in provider.user_data
    plain = EchoProvider()
    _ask(db, "¿qué está barato?", plain)
    assert "Resumen fiscal" not in plain.user_data


def test_invalidacion_de_mis_tesis_lleva_los_criterios(db):
    provider = EchoProvider(reply="Tu tesis de POOL se invalida si el margen bruto baja del 28 % dos trimestres seguidos.")
    resp = _ask(db, "¿cuándo se invalidan mis tesis?", provider)
    assert resp.llm_trace["intent"] == "tesis"
    assert "El margen bruto baja del 28 % dos trimestres seguidos" in provider.user_data
    assert resp.llm_trace["grounding"] == "ok"


def test_contexto_acotado_y_sin_otros_tenants(db):
    provider = EchoProvider()
    _ask(db, "¿qué sabes de mí?", provider)
    data = provider.user_data
    assert len(data) <= 9000
    assert "SECRET" not in data


def test_sin_motor_dca_lo_dice(db, monkeypatch):
    monkeypatch.setattr(user_context, "default_dca_reader", lambda *a: None)
    provider = EchoProvider(reply="Ningún valor tiene nivel DCA disponible todavía (watchlist).")
    resp = _ask(db, "enséñame mi watchlist", provider)
    assert "nivel DCA no disponible" in provider.user_data
    assert "4X" not in provider.user_data
    assert resp.llm_trace["grounding"] == "ok"


def test_anclaje_formatos():
    ctx = "valor 4.000,00 EUR, margen de seguridad +25,0 %, POOL"
    assert ungrounded_numbers("POOL vale 4.000 EUR con un 25 % de margen", ctx) == []
    assert ungrounded_numbers("margen del 26 %", ctx) == [26.0]
    # Recuentos y años no se anclan: «3 valores», «en 2026».
    assert ungrounded_numbers("3 valores en 2026", ctx) == []
    assert ungrounded_tickers("POOL y KKR", ctx) == ["KKR"]


def test_purchase_question_unifies_saved_dca_with_plan_alerts_and_holdings(db, monkeypatch):
    from dataclasses import replace

    from tests.cerebro_seed import fake_dca_reader
    def uber_four(session, tenant, symbols):
        readings = fake_dca_reader(session, tenant, symbols)
        if "UBER" in readings:
            readings["UBER"] = replace(readings["UBER"], level=4, label="4X DCA")
        return readings
    monkeypatch.setattr(user_context, "default_dca_reader", uber_four)
    provider = EchoProvider(reply="UBER tiene nivel DCA 4X DCA guardado. No es una orden de compra.")
    response = _ask(db, "¿Qué debo comprar hoy?", provider)
    assert response.llm_trace["path"] == "personal_context"
    assert "UBER" in provider.user_data and "4X DCA" in provider.user_data
    for block in ["Cartera", "Watchlist", "Tesis", "Avisos", "Diario", "Plan"]:
        assert block in provider.user_data
    assert "4 €" not in response.answer


def test_named_purchase_question_does_not_bypass_personal_snapshot(db):
    provider = EchoProvider()
    response = _ask(db, "¿Qué debo comprar hoy de UBER con mi aportación?", provider)
    assert response.llm_trace["path"] == "personal_context"
    assert "UBER" in provider.user_data and "Plan" in provider.user_data


def test_saved_purchase_context_works_when_ticker_field_is_explicit(db):
    provider = EchoProvider()
    response = asyncio.run(ChatService(provider=provider).answer(db, "¿Qué debo comprar hoy?", "portfolio", "UBER"))
    assert response.llm_trace["path"] == "personal_context"
    assert "UBER" in provider.user_data and "Watchlist" in provider.user_data


def test_purchase_fallback_keeps_plan_before_bounded_dca_candidates(db):
    from app.services.personal_answer import answer_personal_question
    intent = detect_personal_intent("¿Qué debo comprar hoy?")
    response = asyncio.run(answer_personal_question(db, "¿Qué debo comprar hoy?", intent, None, use_llm=False))
    assert "300,00 EUR" in response.answer
    assert "no cotizaciones en directo" in response.answer
    assert "2026-10-01" in response.answer
