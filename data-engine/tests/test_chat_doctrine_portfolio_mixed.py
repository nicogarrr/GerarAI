"""#11: preguntas mixtas carta + cartera («¿Qué diría Numantia de mi cartera?»).

Antes, con al menos una posición guardada, iban al volcado de posiciones (sin
carta) y, sin él, a la abstención general por el «mi». Ahora la síntesis recibe
los fragmentos de la carta y las posiciones juntos.
"""

import asyncio
import json
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.llm import LLMResponse, Message, Usage
from app.models import Company
from app.models.entities import Base, KnowledgeChunk, KnowledgeDocument, Position
from app.services.chat_service import ChatService

PAD = "Texto de relleno sobre la gestion del fondo y su historia. " * 20
REPARTO = (
    "En la cartera repartimos entre negocios aburridos y estables, que son el grueso, "
    "e ideas con mas riesgo y mucho potencial, que pesan poco."
)
RESPUESTA = (
    "Numantia explica en su carta que reparte la cartera entre negocios aburridos y estables, "
    "que son el grueso, e ideas con más riesgo que pesan poco. Tu cartera guardada solo tiene "
    "Apple, así que estaría entera en el lado de los negocios estables."
)


class _Provider:
    name = "stub"

    def __init__(self) -> None:
        self.requests: list = []

    async def complete(self, request):
        self.requests.append(request)
        return LLMResponse(
            message=Message("assistant", RESPUESTA),
            usage=Usage(input_tokens=10, output_tokens=10, total_tokens=20),
            model="stub", provider="stub", request_id="mixed-test",
        )

    async def generate_json(self, *args, **kwargs):
        raise AssertionError("no se espera JSON en esta ruta")


def _company(session, ticker, name):
    session.add(Company(
        ticker=ticker, name=name, exchange="NYSE", currency="USD", sector="Tecnología", industry="x",
        company_type="operating", valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    ))


@pytest.fixture()
def db():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    session.info["tenant_id"] = 1
    _company(session, "AAPL", "Apple Inc.")
    doc = KnowledgeDocument(
        tenant_id=1, title="Numantia Patrimonio - Carta 2025", author="Numantia Patrimonio",
        document_type="fund_letter", status="ready",
    )
    session.add(doc)
    session.flush()
    session.add(KnowledgeChunk(
        tenant_id=1, knowledge_document_id=doc.id, chunk_index=0, content=PAD + REPARTO + " " + PAD, page_number=1,
    ))
    apple = session.query(Company).filter_by(ticker="AAPL").one()
    session.add(Position(
        tenant_id=1, company_id=apple.id, quantity=Decimal(10), average_cost=Decimal(150),
        market_price=Decimal(200), market_value=Decimal(2000), currency="USD",
    ))
    session.commit()
    return session


def _ask(db, question):
    provider = _Provider()
    resp = asyncio.run(ChatService(provider=provider).answer(db, question, "portfolio", None))
    return resp, provider


def _payload(provider) -> dict:
    assert provider.requests, "la pregunta no llegó a la síntesis"
    return json.loads(provider.requests[-1].messages[-1].content)


@pytest.mark.parametrize("question", [
    "¿Qué diría Numantia de mi cartera?",
    "¿Qué principios aplica la carta de Numantia a mi cartera?",
])
def test_pregunta_mixta_usa_la_carta_y_las_posiciones(db, question):
    resp, provider = _ask(db, question)

    payload = _payload(provider)
    assert [row["ticker"] for row in payload["portfolio_positions"]] == ["AAPL"]
    assert any("aburridos" in item["text"] for item in payload["doctrine_context"])
    assert resp.model == "stub"
    assert "Numantia" in resp.answer
    types = {source.get("type") for source in resp.sources}
    assert {"knowledge_chunk", "position"} <= types
    assert (resp.llm_trace or {}).get("mixed") == "doctrine_portfolio"


def test_pregunta_de_cartera_sin_carta_sigue_en_el_resumen(db):
    resp, provider = _ask(db, "¿Cómo va mi cartera?")
    assert (resp.llm_trace or {}).get("path") == "portfolio_overview"
    assert not provider.requests


def test_orden_de_compra_no_entra_en_la_ruta_mixta(db):
    resp, provider = _ask(db, "¿Compro más para mi cartera según Numantia?")
    assert (resp.llm_trace or {}).get("mixed") is None
    for request in provider.requests:
        assert "portfolio_positions" not in json.loads(request.messages[-1].content) or not json.loads(
            request.messages[-1].content
        ).get("portfolio_positions")


def test_sin_carta_del_autor_no_se_inventa(db):
    resp, provider = _ask(db, "¿Qué diría Buffett de mi cartera?")
    assert (resp.llm_trace or {}).get("mixed") is None
    assert not provider.requests
