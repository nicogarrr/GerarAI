import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact, MarketPrice, NewsEvent, Position, ThesisVersion
from app.models.entities import Base
from app.services.brain_data_tools import answer_data_question
from app.services.chat_service import ChatService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def company(db, ticker):
    row = Company(ticker=ticker, name=ticker + " Inc", currency="USD", exchange="NASDAQ", company_type="operating", valuation_model="unassigned")
    db.add(row)
    db.flush()
    return row


def test_quote_and_ratio_are_dated_sourced_and_ignore_other_tenant_and_future(db):
    a = company(db, "AAPL")
    db.add_all([
        MarketPrice(company_id=a.id, date=date.today(), close=Decimal("200"), source="yahoo"),
        MarketPrice(company_id=a.id, date=date.today() + timedelta(days=1), close=Decimal("999"), source="yahoo"),
        FinancialFact(tenant_id=1, company_id=a.id, metric="eps_diluted", value=Decimal("10"), unit="USD/shares", period=f"{date.today().year-1}-09-27:FY", fiscal_year=date.today().year-1, fiscal_quarter="FY", source_type="SEC", is_reported=True),
        FinancialFact(tenant_id=2, company_id=a.id, metric="eps_diluted", value=Decimal("1"), unit="USD/shares", period=f"{date.today().year}:FY", fiscal_year=date.today().year, fiscal_quarter="FY", source_type="SEC", is_reported=True),
    ])
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "¿Precio actual de AAPL y su PER?", "portfolio", None))
    assert "200,00 USD" in response.answer
    assert "20,00 veces" in response.answer
    assert "999" not in response.answer
    assert "no es una cotización en directo" in response.answer.lower()
    assert response.llm_trace["provider_calls"] == 0
    assert all(source["url"] for source in response.sources)


def test_comparison_names_both_and_missing_values_without_llm(db):
    company(db, "AAPL")
    company(db, "MSFT")
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "Compara AAPL y MSFT", "portfolio", None))
    assert "AAPL" in response.answer and "MSFT" in response.answer
    assert "sin cotización" in response.answer
    assert response.llm_trace["provider_calls"] == 0


def test_news_scoped_to_owned_positions_and_tenant(db):
    a = company(db, "AAPL")
    b = company(db, "MSFT")
    db.add(Position(tenant_id=1, company_id=a.id, quantity=1, average_cost=10, currency="USD", market_value=10, as_of=date.today()))
    db.add_all([
        NewsEvent(tenant_id=1, company_id=a.id, title="Apple anuncia resultados", source="SEC", url="https://example.com/apple"),
        NewsEvent(tenant_id=2, company_id=a.id, title="Privado tenant 2", source="SEC"),
        NewsEvent(tenant_id=1, company_id=b.id, title="No es mi posición", source="SEC"),
    ])
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "¿Qué noticias hay de mis empresas?", "portfolio", None))
    assert "Apple anuncia resultados" in response.answer
    assert "Privado" not in response.answer and "No es mi posición" not in response.answer
    assert response.sources[0]["url"] == "https://example.com/apple"


def test_theses_latest_draft_not_active_and_other_tenant_hidden(db):
    a, b = company(db, "AAPL"), company(db, "MSFT")
    def thesis(comp, version, status, tenant=1):
        return ThesisVersion(tenant_id=tenant, company_id=comp.id, version=version, status=status, thesis_markdown="Texto", executive_summary="Resumen")
    db.add_all([thesis(a, 1, "published"), thesis(a, 2, "draft"), thesis(b, 1, "published"), thesis(b, 9, "draft", 2)])
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "¿Qué tesis tengo activas?", "portfolio", None))
    assert "MSFT: tesis v1 (publicada)" in response.answer
    assert "AAPL: v2, no activa" in response.answer
    assert "v9" not in response.answer
    assert len(response.sources) == 3
    assert "AAPL: tesis v1 (publicada)" in response.answer


def test_no_tenant_no_tools_and_no_trading(db):
    assert answer_data_question(db, "Compra AAPL al precio actual") is None
    db.info.clear()
    assert answer_data_question(db, "¿Qué tesis tengo activas?") is None


def test_author_without_fragment_offers_alternative_without_provider():
    from app.schemas import ChatResponse
    from app.services.chat_synthesis_service import ChatSynthesisService
    response = asyncio.run(ChatSynthesisService(provider=None).synthesize_general(
        question="Dame una cita de Munger sobre el riesgo", baseline=ChatResponse(answer="", sources=[]),
    ))
    assert "fragmento verificable" in response.answer
    assert "sin atribuírselo" in response.answer
    assert response.llm_trace["provider_calls"] == 0


def test_general_scope_and_clock_are_not_financial_refusals():
    from app.services.chat_synthesis_service import _clock_context, _general_scope
    assert _general_scope("¿Cuál es la capital de Australia?") == "ordinary"
    assert _general_scope("¿Qué hora es en Tokio?") == "ordinary"
    assert _clock_context("¿Qué hora es en Tokio?")["timezone"] == "Asia/Tokyo"
    assert _clock_context("Precio de AAPL") is None


def test_general_geography_uses_model_with_company_page_context(db, monkeypatch):
    from app.schemas import ChatPageContext, ChatResponse
    from app.services.chat_synthesis_service import ChatSynthesisService
    company(db, "AAPL")
    db.commit()
    async def general(self, **kwargs):
        assert kwargs["question"] == "¿Cuál es la capital de Australia?"
        return ChatResponse(answer="La capital de Australia es Canberra.", sources=[])
    monkeypatch.setattr(ChatSynthesisService, "synthesize_general", general)
    monkeypatch.setattr(ChatService, "_deterministic_answer", lambda *args: ChatResponse(answer="", sources=[]))
    response = asyncio.run(ChatService().answer(
        db, "¿Cuál es la capital de Australia?", "portfolio", None,
        page=ChatPageContext(path="/research/AAPL", label="Apple", ticker="AAPL"),
    ))
    assert "Canberra" in response.answer


def test_general_clock_calls_model_with_real_clock_not_a_refusal():
    import json
    from app.llm import LLMResponse, Message, Usage
    from app.schemas import ChatResponse
    from app.services.chat_synthesis_service import ChatSynthesisService
    class Provider:
        def __init__(self):
            self.requests = []
        async def complete(self, request):
            self.requests.append(request)
            clock = json.loads(request.messages[-1].content)["current_time_context"]
            return LLMResponse(message=Message("assistant", f"En Tokio son las {clock['local_time'][11:16]}."),
                               usage=Usage(input_tokens=10, output_tokens=10, total_tokens=20),
                               model="stub", provider="stub", request_id="clock-test")
    provider = Provider()
    response = asyncio.run(ChatSynthesisService(provider).synthesize_general(
        question="¿Qué hora es en Tokio?", baseline=ChatResponse(answer="", sources=[]),
    ))
    assert provider.requests
    assert response.answer.startswith("En Tokio son las")
    assert response.model == "stub"
