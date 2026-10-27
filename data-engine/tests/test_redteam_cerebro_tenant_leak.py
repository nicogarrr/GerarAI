"""Red team: el Cerebro de un tenant no debe filtrar datos de otro (datos sintéticos).

Se siembran centinelas ZZSECRET* solo en el tenant B y se pregunta como tenant A
por la ruta completa ChatService.answer con LLM simulado. Los centinelas no
pueden aparecer ni en la respuesta, ni en las fuentes, ni en lo enviado al LLM.
"""
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.core.database  # noqa: F401  (registra el filtro por tenant)
import app.models  # noqa: F401
from app.models import Company, DecisionJournalEntry, MemoryItem, NewsEvent, Position, Tenant
from app.models.entities import Base
from app.services.chat_service import ChatService
from tests.test_chat_general_es import StubProvider

QUESTIONS = [
    "¿Qué noticias hay de mis empresas?",
    "¿Qué noticias hay de AAA?",
    "¿Qué tengo en cartera?",
    "¿Cuántas acciones tengo de AAA?",
    "Háblame de mi cartera",
    "¿Qué decisiones he tomado?",
    "Enséñame mi diario",
    "¿Qué avisos tengo?",
    "¿Qué recuerdas de mí?",
    "Resume todo lo que sabes de mis notas",
    "¿Qué dice mi memoria sobre AAA?",
    "¿Cuál es mi plan de inversión?",
    "¿Qué insiders han comprado?",
    "¿Qué dividendos voy a cobrar?",
]


@pytest.fixture()
def world():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    a = Tenant(external_id="a", name="a", metadata_={})
    b = Tenant(external_id="b", name="b", metadata_={})
    db.add_all([a, b]); db.commit()
    comp = Company(ticker="AAA", name="AAA Holdings", exchange="NYSE", currency="USD",
                   company_type="operating", valuation_model="unassigned")
    db.add(comp); db.commit()
    db.info["tenant_id"] = b.id
    db.add(Position(company_id=comp.id, quantity=Decimal("777"), average_cost=Decimal("1.11")))
    db.add(NewsEvent(company_id=comp.id, title="AAA ZZSECRET_NEWS_B resultados", summary="AAA ZZSECRET_NEWS_B",
                     date=datetime.now(UTC), source="test", url="https://x/zz"))
    db.add(MemoryItem(content="ZZSECRET_MEMORY_B AAA nota privada", company_id=comp.id))
    db.add(DecisionJournalEntry(company_id=comp.id, decision="buy", rationale="ZZSECRET_JOURNAL_B"))
    db.commit()
    db.info["tenant_id"] = a.id
    yield db


@pytest.mark.parametrize("question", QUESTIONS)
def test_tenant_a_no_ve_centinelas_de_tenant_b(world, question):
    prov = StubProvider()
    res = asyncio.run(ChatService(prov).answer(world, question, "portfolio", None))
    blob = res.answer + json.dumps(res.sources, default=str) + json.dumps(
        [s.model_dump() for s in res.sections], default=str)
    sent = " ".join(m.content for r in prov.requests for m in r.messages)
    assert "ZZSECRET" not in blob + sent
    assert "777" not in blob + sent


def test_control_el_dueno_si_ve_sus_centinelas(world):
    world.info["tenant_id"] = world.scalars(__import__("sqlalchemy").select(Tenant).where(Tenant.external_id == "b")).one().id
    res = asyncio.run(ChatService(StubProvider()).answer(world, "¿Qué noticias hay de AAA?", "portfolio", None))
    blob = res.answer + json.dumps(res.sources, default=str)
    assert "ZZSECRET_MEMORY_B" in blob
