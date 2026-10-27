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
from app.schemas import ChatRequest, ChatResponse
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
    # 2 s: margen para el trabajo previo a la sintesis (resolver empresa, BD).
    # La sintesis cuelga 30 s, asi que el plazo vence siempre dentro de ella.
    monkeypatch.setattr(interactive_deadline, "get_settings",
                        lambda: SimpleNamespace(chat_total_timeout_seconds=2.0))


@pytest.fixture
def instant_baseline(monkeypatch):
    """La recuperacion determinista no consume plazo: el plazo vence en la sintesis.

    No se simula el comportamiento bajo prueba (el vencimiento del plazo en la
    sintesis), solo se quita la dependencia de la velocidad del runner de la
    fase previa.
    """
    monkeypatch.setattr(
        ChatService, "_deterministic_answer",
        lambda self, db, question, scope, ticker: ChatResponse(
            answer="BASELINE", sources=[], model="deterministic", confidence=0.5),
    )


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


def test_answer_returns_deterministic_on_total_deadline(db, short_deadline, hanging_synthesis, instant_baseline):
    service = ChatService()
    start = time.monotonic()
    response = asyncio.run(service.answer(db, "qué es el margen operativo", "general", None))
    assert time.monotonic() - start < 10
    _assert_deadline_fallback(response)


def test_route_returns_deterministic_on_total_deadline(db, short_deadline, hanging_synthesis, instant_baseline):
    from app.api.routes.chat import chat
    payload = ChatRequest(question="qué es el margen operativo", scope="general")
    start = time.monotonic()
    response = asyncio.run(chat(payload, db))
    assert time.monotonic() - start < 10
    _assert_deadline_fallback(response)


def test_answer_deadline_spent_in_recovery_returns_baseline(db, monkeypatch):
    """Plazo agotado en la recuperacion previa (RAG lento): responde el baseline
    determinista con fallback_reason chat_total_deadline, sin llegar a sintetizar."""
    monkeypatch.setattr(interactive_deadline, "get_settings",
                        lambda: SimpleNamespace(chat_total_timeout_seconds=.2))

    def slow_baseline(self, db, question, scope, ticker):
        time.sleep(.4)  # la recuperacion consume todo el plazo
        return ChatResponse(answer="BASELINE", sources=[], model="deterministic", confidence=0.5)

    async def synth_must_not_run(*args, **kwargs):
        raise AssertionError("no debe sintetizar con el plazo agotado")

    monkeypatch.setattr(ChatService, "_deterministic_answer", slow_baseline)
    monkeypatch.setattr(
        "app.services.chat_synthesis_service.ChatSynthesisService.synthesize_general",
        synth_must_not_run)
    response = asyncio.run(ChatService().answer(db, "qué es el margen operativo", "general", None))
    assert response.model == "deterministic"
    assert response.llm_trace["fallback_reason"] == "chat_total_deadline"
    assert response.answer == "BASELINE"


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
