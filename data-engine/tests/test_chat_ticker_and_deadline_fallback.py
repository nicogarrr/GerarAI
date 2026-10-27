"""Regresiones del piloto: falso positivo de ticker ES y TimeoutError sin capturar."""
import asyncio
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.llm import interactive_deadline
from app.models.entities import Base, Company
from app.schemas import ChatRequest
from app.services.chat_service import ChatService


@pytest.fixture
def db():
    # La ruta corre el servicio en un hilo del pool: StaticPool comparte la
    # unica conexion SQLite en memoria entre hilos.
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _es_company(db: Session) -> Company:
    company = Company(
        ticker="ES", name="Eversource Energy", exchange="NYSE", currency="USD",
        sector="Utilities", industry="Utilities", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_common_word_es_does_not_resolve_ticker(db):
    _es_company(db)
    service = ChatService()
    question = "Explica en dos frases qué es el margen operativo"
    assert service._resolve_company(db, question, "general", None) is None
    assert service._explicit_mention(db, question) is None
    assert service._resolve_company(db, "que es la deuda neta", "general", None) is None


def test_uppercase_es_with_company_cue_still_resolves(db):
    company = _es_company(db)
    service = ChatService()
    assert service._resolve_company(db, "precio de ES hoy", "general", None) == company


@pytest.fixture
def short_deadline(monkeypatch):
    # 2 s y no .3: la recuperacion previa a la sintesis (_deterministic_answer)
    # tarda mas de .3 s en un runner cargado y entonces el plazo vence ANTES
    # de sintetizar: devuelve el baseline (mismo fallback_reason) y no el
    # texto «tardó demasiado» que este test comprueba. La sintesis cuelga 30 s,
    # asi que 2 s sigue disparando el plazo.
    monkeypatch.setattr(interactive_deadline, "get_settings",
                        lambda: SimpleNamespace(chat_total_timeout_seconds=2.0))


@pytest.fixture
def hanging_synthesis(monkeypatch):
    """Tiempo consumido fuera del guard por llamada (RAG lento, secciones...)."""
    async def hang(*args, **kwargs):
        await asyncio.sleep(30)
    monkeypatch.setattr(
        "app.services.chat_synthesis_service.ChatSynthesisService.synthesize_general", hang)


def _assert_deadline_fallback(response):
    assert response.model == "deterministic"
    assert response.llm_trace["fallback_reason"] == "chat_total_deadline"
    assert "tardó demasiado" in response.answer


def test_answer_returns_deterministic_on_total_deadline(db, short_deadline, hanging_synthesis):
    service = ChatService()
    start = time.monotonic()
    response = asyncio.run(service.answer(db, "qué es el margen operativo", "general", None))
    assert time.monotonic() - start < 10
    _assert_deadline_fallback(response)


def test_route_returns_deterministic_on_total_deadline(db, short_deadline, hanging_synthesis):
    from app.api.routes.chat import chat
    payload = ChatRequest(question="qué es el margen operativo", scope="general")
    start = time.monotonic()
    response = asyncio.run(chat(payload, db))
    assert time.monotonic() - start < 10
    _assert_deadline_fallback(response)


def _mk(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=f"Corp {ticker}", exchange="X", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_one_letter_ticker_uppercase_with_cue_resolves(db):
    t = _mk(db, "T")
    v = _mk(db, "V")
    service = ChatService()
    assert service._resolve_company(db, "tesis de T", "general", None) == t
    assert service._resolve_company(db, "precio de V", "general", None) == v


def test_one_letter_ticker_without_cue_does_not_resolve(db):
    _mk(db, "T")
    service = ChatService()
    assert service._resolve_company(db, "how is T doing", "general", None) is None


def test_digit_tickers_resolve(db):
    hk = _mk(db, "0700.HK")
    jp = _mk(db, "7203.T")
    service = ChatService()
    assert service._resolve_company(db, "analiza 0700.HK", "general", None) == hk
    assert service._resolve_company(db, "tesis de 7203.T", "general", None) == jp


def test_existing_false_positive_guards_hold(db):
    _mk(db, "ES")
    _mk(db, "META")
    service = ChatService()
    assert service._resolve_company(db, "es un buen momento", "general", None) is None
    assert service._resolve_company(db, "mi meta de ahorro", "portfolio", None) is None
