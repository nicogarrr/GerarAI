import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Company,
    FinancialFact,
    InsiderTransaction,
    MarketPrice,
    NewsEvent,
    Position,
    ThesisVersion,
)
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


@pytest.fixture(autouse=True)
def _no_live_dividend_sync(monkeypatch):
    """Los tests nunca llaman al proveedor: sin datos propios responde «no tengo»."""
    from app.services.dividend_ingestion_service import DividendIngestionService

    async def unavailable(self, db_, *, ticker):
        return {"ticker": ticker, "status": "unavailable", "inserted": 0, "existing": 0}

    monkeypatch.setattr(DividendIngestionService, "sync_company", unavailable)


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
    assert "$200.00" in response.answer
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
        NewsEvent(tenant_id=1, company_id=a.id, title="Resultados de AAPL", source="SEC", url="https://example.com/apple"),
        NewsEvent(tenant_id=2, company_id=a.id, title="Privado tenant 2", source="SEC"),
        NewsEvent(tenant_id=1, company_id=b.id, title="No es mi posición", source="SEC"),
    ])
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "¿Qué noticias hay de mis empresas?", "portfolio", None))
    assert "Resultados de AAPL" in response.answer
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


def test_mixed_quote_and_fcf_margin_answers_both_without_provider(db):
    a = company(db, "AAPL")
    db.add(MarketPrice(company_id=a.id, date=date.today(), close=Decimal("200"), source="yahoo"))
    for metric, value in [("revenue", "100"), ("free_cash_flow", "25")]:
        db.add(FinancialFact(tenant_id=1, company_id=a.id, metric=metric, value=Decimal(value), unit="USD", period="2025:FY", fiscal_year=2025, source_type="SEC", is_reported=True))
    db.commit()
    response = asyncio.run(ChatService().answer(db, "¿Cuál es el margen FCF de AAPL y cuál es su precio actual?", "portfolio", None))
    assert "$200.00" in response.answer
    assert "25,00 %" in response.answer
    assert response.llm_trace["provider_calls"] == 0
    assert len(response.sources) == 3
    assert all(source["url"] for source in response.sources)


def _dividend(db, comp, ex, amount, pay=None, tenant=1):
    from app.models import DividendRecord
    db.add(DividendRecord(tenant_id=tenant, company_id=comp.id, ex_date=ex, pay_date=pay, amount=Decimal(amount), currency="USD", source="fmp"))


def test_company_dividend_by_name_next_and_last_declared(db):
    ko = Company(ticker="KO", name="Coca-Cola Co", currency="USD", exchange="NYSE", company_type="operating", valuation_model="unassigned")
    db.add(ko)
    db.flush()
    _dividend(db, ko, date.today() + timedelta(days=20), "0.53", date.today() + timedelta(days=45))
    _dividend(db, ko, date.today() - timedelta(days=70), "0.51")
    db.commit()
    db.info.pop("tenant_id", None)
    _dividend(db, ko, date.today() + timedelta(days=20), "9.99", tenant=2)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "¿Qué dividendo paga Coca-Cola y cuándo es el próximo?", "portfolio", None))
    assert "Próximo declarado" in response.answer and "$0.53" in response.answer
    assert "$0.51" in response.answer and "9,99" not in response.answer
    assert response.llm_trace["provider_calls"] == 0
    assert response.sources and all(s["url"].startswith("/research/KO") for s in response.sources)


def test_company_without_dividends_says_unavailable(db):
    ko = Company(ticker="KO", name="Coca-Cola Co", currency="USD", exchange="NYSE", company_type="operating", valuation_model="unassigned")
    db.add(ko)
    db.commit()
    response = asyncio.run(ChatService().answer(db, "¿Qué dividendo paga Coca-Cola y cuándo es el próximo?", "portfolio", None))
    assert "No tengo dividendos guardados de KO" in response.answer
    assert response.sources == []


def test_portfolio_dividends_this_year_only_own_open_positions(db):
    a = company(db, "AAA")
    b = company(db, "BBB")
    c = company(db, "CCC")
    today = date.today()
    for comp, qty in ((a, "10"), (b, "5")):
        db.add(Position(tenant_id=1, company_id=comp.id, quantity=Decimal(qty), average_cost=Decimal("10"), currency="USD", as_of=today, market_value=Decimal("100")))
    _dividend(db, a, date(today.year, 1, 15), "1.00")
    _dividend(db, a, date(today.year, 7, 15), "1.50")
    _dividend(db, c, date(today.year, 3, 1), "5.00")
    db.commit()
    response = asyncio.run(ChatService().answer(db, "¿Qué dividendos cobrará mi cartera este año?", "portfolio", None))
    assert "AAA: 2 pago(s)" in response.answer and "$25.00" in response.answer
    assert "Sin dividendos guardados: BBB" in response.answer
    assert "CCC" not in response.answer
    assert response.sources and response.llm_trace["provider_calls"] == 0


def test_dividend_question_without_company_or_portfolio_is_not_hijacked(db):
    from app.services.brain_data_tools import answer_data_question
    assert answer_data_question(db, "¿Qué es un dividendo?") is None


def _thesis(db, comp, version, status, mos, tenant=1):
    db.add(ThesisVersion(tenant_id=tenant, company_id=comp.id, version=version, status=status, thesis_markdown="x", executive_summary="x",
                         current_price=Decimal("342.62"), bear_value=Decimal("60"), base_value=Decimal("120"), bull_value=Decimal("180"),
                         expected_value=Decimal("120.4"), margin_of_safety=Decimal(mos)))


def test_thesis_margin_uses_latest_published_version_only(db):
    a = company(db, "AAPL")
    _thesis(db, a, 10, "published", "0.10")
    _thesis(db, a, 11, "published", "-0.649")
    _thesis(db, a, 12, "draft", "0.5")
    db.commit()
    response = asyncio.run(ChatService().answer(db, "¿Cuánto margen de seguridad tiene Apple según mi tesis? AAPL", "portfolio", None))
    assert "v11" in response.answer and "-64,90 %" in response.answer
    assert "fórmula no verificada" in response.answer
    assert "no es un margen comparable" in response.answer
    assert "bajista $60.00" in response.answer and "no es la cotización actual" in response.answer
    assert "50,00" not in response.answer
    assert response.sources[0]["url"] == "/research/AAPL?view=thesis"
    assert response.llm_trace["provider_calls"] == 0


def test_thesis_margin_draft_only_and_missing_are_honest(db):
    a = company(db, "AAPL")
    company(db, "MSFT")
    _thesis(db, a, 1, "draft", "0.2")
    db.commit()
    draft = asyncio.run(ChatService().answer(db, "¿Qué margen de seguridad tiene AAPL según mi tesis?", "portfolio", None))
    assert "no publicada" in draft.answer and "0,20" not in draft.answer
    assert "Publica la tesis" in draft.answer
    none = asyncio.run(ChatService().answer(db, "¿Qué margen de seguridad tiene MSFT según mi tesis?", "portfolio", None))
    assert "No hay ninguna tesis guardada de MSFT" in none.answer


def _plan_setup(db, targets):
    from app.models import InvestmentPlan, Portfolio
    p = Portfolio(name="P", base_currency="USD", is_default=True)
    db.add(p)
    db.flush()
    db.add(InvestmentPlan(portfolio_id=p.id, monthly_contribution=Decimal("500"), start_date=date(2026, 1, 1), horizon_years=20, target_allocations=targets))


def test_plan_question_reads_plan_and_underweight_targets(db):
    a = company(db, "AAA")
    a.sector = "Tech"
    _plan_setup(db, [{"kind": "sector", "label": "Tech", "target_pct": 100, "band_pct": 5}, {"kind": "ticker", "label": "BBB", "target_pct": 20, "band_pct": 5}])
    db.add(Position(tenant_id=1, company_id=a.id, quantity=Decimal("1"), average_cost=Decimal("100"), currency="USD", base_currency="USD", as_of=date.today(), market_value=Decimal("100"), market_value_base=Decimal("100")))
    db.commit()
    response = asyncio.run(ChatService().answer(db, "Tengo 500 € este mes. Según mi plan, ¿qué compro?", "portfolio", None))
    assert "$500.00 al mes" in response.answer
    assert "Objetivos por debajo de su banda" in response.answer
    assert "BBB: 0,00 % actual frente a 20,00 % objetivo, hueco de $20.00" in response.answer
    assert "Tech:" not in response.answer
    assert response.sources == [{"type": "investment_plan", "id": "plan", "title": "Plan de inversión", "url": "/plan"}]
    assert "Valor de la cartera usado: $100.00" in response.answer
    assert "no una orden" in response.answer
    assert response.llm_trace["provider_calls"] == 0


def test_plan_question_without_plan_is_honest(db):
    response = asyncio.run(ChatService().answer(db, "Tengo 500 € este mes. Según mi plan, ¿qué compro?", "portfolio", None))
    assert "No tienes un plan de inversión guardado" in response.answer
    assert response.sources == []


def test_company_without_records_is_synced_on_demand_before_answering(db, monkeypatch):
    from app.services.dividend_ingestion_service import DividendIngestionService

    ko = Company(ticker="KO", name="Coca-Cola Co", currency="USD", exchange="NYSE", company_type="operating", valuation_model="unassigned")
    db.add(ko)
    db.commit()
    calls = []

    async def fake_sync(self, db_, *, ticker):
        calls.append(ticker)
        _dividend(db_, ko, date.today() - timedelta(days=30), "0.51")
        db_.commit()
        return {"ticker": ticker, "status": "ok", "inserted": 1, "existing": 0}

    monkeypatch.setattr(DividendIngestionService, "sync_company", fake_sync)
    response = asyncio.run(ChatService().answer(db, "¿Qué dividendo paga Coca-Cola y cuándo es el próximo?", "portfolio", None))
    assert calls == ["KO"]
    assert "$0.51" in response.answer


def _news(db_, company_, title, summary=None, source="MarketBeat", tenant=1):
    from datetime import datetime
    row = NewsEvent(tenant_id=tenant, company_id=company_.id, title=title, summary=summary,
                    source=source, date=datetime(2026, 10, 19, 9, 54))
    db_.add(row)
    return row


def test_news_question_naming_a_company_is_scoped_to_it(db):
    """"noticias de ASTS y mi cartera" no vuelca las noticias de otras posiciones."""
    asts = company(db, "ASTS")
    amzn = company(db, "AMZN")
    db.add(Position(tenant_id=1, company_id=amzn.id, quantity=10, average_cost=185, currency="USD",
                    market_value=2221, market_value_base=2221, as_of=date.today()))
    _news(db, amzn, "AMZN Amazon.com, Inc. $AMZN Shares Sold by Cooper Investors PTY Ltd. "
                    "Amazon.com, Inc. $AMZN Shares Sold by Cooper Investors PTY Ltd. MarketBeat",
          summary="Cooper Investors sold Amazon shares")
    _news(db, asts, "AST SpaceMobile anuncia acuerdo con operadora europea",
          summary="AST SpaceMobile firma un acuerdo comercial", source="SEC")
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(
        db, "¿Qué noticias hay de ASTS últimamente y cómo afectan a mi cartera?", "portfolio", None))
    assert response.llm_trace["path"] == "company_news"
    assert "AST SpaceMobile anuncia acuerdo" in response.answer
    assert "Amazon" not in response.answer and "AMZN" not in response.answer
    assert all("AMZN" not in (src["title"] or "") for src in response.sources)


def test_company_news_without_rows_says_so_without_portfolio_dump(db):
    asts = company(db, "ASTS")
    amzn = company(db, "AMZN")
    db.add(Position(tenant_id=1, company_id=amzn.id, quantity=10, average_cost=185, currency="USD",
                    market_value=2221, market_value_base=2221, as_of=date.today()))
    _news(db, amzn, "AMZN Amazon.com shares rally on AWS growth", summary="Amazon shares rose")
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(
        db, "¿Qué noticias hay de ASTS últimamente y cómo afectan a mi cartera?", "portfolio", None))
    assert response.llm_trace["path"] == "company_news"
    assert "No hay noticias guardadas de ASTS" in response.answer
    assert "Amazon" not in response.answer


def test_company_news_declares_holding_weight_without_inventing_impact(db):
    asts = company(db, "ASTS")
    amzn = company(db, "AMZN")
    db.add(Position(tenant_id=1, company_id=asts.id, quantity=300, average_cost=40, currency="USD",
                    market_value=12000, market_value_base=9000, as_of=date.today()))
    db.add(Position(tenant_id=1, company_id=amzn.id, quantity=10, average_cost=185, currency="USD",
                    market_value=2221, market_value_base=1000, as_of=date.today()))
    _news(db, asts, "AST SpaceMobile lanza dos BlueBird mas", summary="AST SpaceMobile lanzo", source="SEC")
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(
        db, "¿Qué noticias hay de ASTS y cómo afectan a mi cartera?", "portfolio", None))
    assert response.llm_trace["path"] == "company_news"
    assert "300,00 acciones de ASTS" in response.answer
    assert "90,00 % de tu cartera" in response.answer
    assert "No calculo el impacto de cada noticia" in response.answer


def test_per_without_verified_eps_explains_what_is_missing(db):
    a = company(db, "AAPL")
    db.add(MarketPrice(company_id=a.id, date=date.today(), close=Decimal("200"), source="yahoo"))
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "¿Precio actual de AAPL y su PER?", "portfolio", None))
    assert "PER: sin dato calculable guardado" in response.answer
    assert "hace falta un precio reciente y un BPA anual positivo" in response.answer
    assert response.llm_trace["provider_calls"] == 0


def test_news_drops_ticker_prefix_and_foreign_company_stories(db):
    a = Company(ticker="MSFT", name="Microsoft Corp", currency="USD", exchange="NASDAQ", company_type="operating", valuation_model="unassigned")
    g = Company(ticker="GOOGL", name="Alphabet Inc", currency="USD", exchange="NASDAQ", company_type="operating", valuation_model="unassigned")
    db.add_all([a, g])
    db.flush()
    db.add(Position(tenant_id=1, company_id=a.id, quantity=1, average_cost=10, currency="USD", market_value=10, as_of=date.today()))
    db.add(Position(tenant_id=1, company_id=g.id, quantity=1, average_cost=10, currency="USD", market_value=10, as_of=date.today()))
    db.add_all([
        # El feed pega el ticker delante del titular.
        NewsEvent(tenant_id=1, company_id=a.id, title="MSFT The Bet Behind Microsoft's Rally", summary="Microsoft sigue creciendo", source="Yahoo"),
        # Noticia de otra empresa (AEP) ligada al ticker GOOGL por el feed.
        NewsEvent(tenant_id=1, company_id=g.id, title="Fuel Cell Deal Could Be A Game Changer For American Electric Power", summary="American Electric Power plans to invest", source="Yahoo"),
    ])
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "¿Qué noticias hay de mis empresas?", "portfolio", None))
    assert "MSFT: MSFT" not in response.answer
    assert "MSFT: 'The Bet Behind Microsoft's Rally'" in response.answer
    assert "American Electric Power" not in response.answer
    assert all("American Electric Power" not in (src["title"] or "") for src in response.sources)
def insider_tx(db, ticker, code, value, tx_date, tenant=1, insider="Cook Timothy D"):
    row = InsiderTransaction(
        tenant_id=tenant, fingerprint=f"{ticker}-{code}-{tx_date}-{value}-{tenant}",
        filing_id=0, accession_number=f"0001-{tx_date}", form="4",
        issuer_ticker=ticker, insider=insider, role="officer", officer_title="CEO",
        multi_reporter=False, code=code, shares=100.0, price=50.0, value=value,
        tx_date=tx_date, source_url=f"https://www.sec.gov/Archives/{ticker}-{tx_date}.xml",
    )
    db.add(row)
    db.flush()
    return row


def test_insider_by_ticker_lists_sec_dated_trades_and_hides_other_tenant(db):
    a = company(db, "AAPL")
    insider_tx(db, "AAPL", "P", 5000.0, "2026-10-01", insider="Cook Timothy D")
    insider_tx(db, "AAPL", "S", 9000.0, "2026-10-10", insider="Jain Ajit")
    db.info["tenant_id"] = 2
    insider_tx(db, "AAPL", "P", 1.0, "2026-10-11", tenant=2)  # otro tenant, invisible
    db.commit()
    db.info["tenant_id"] = 1
    response = answer_data_question(db, "¿Qué operaciones insider hay de AAPL?")
    assert response is not None
    assert "Cook Timothy D compró" in response.answer
    assert "Jain Ajit vendió" in response.answer
    assert "SEC Form 4" in response.answer
    assert "10 oct 2026" in response.answer  # fecha en español natural, nunca ISO
    assert "2026-10-10" not in response.answer
    assert "$9,000.00" in response.answer
    assert "11 oct 2026" not in response.answer  # del tenant 2
    assert response.llm_trace["path"] == "company_insider"
    assert all(source["url"].startswith("https://www.sec.gov/") for source in response.sources)


def test_insider_by_ticker_without_records_is_honest(db):
    company(db, "MSFT")
    db.commit()
    response = answer_data_question(db, "¿Hay compras insider de MSFT?")
    assert response is not None
    assert "No tengo operaciones insider guardadas de MSFT" in response.answer
    assert "No he consultado la SEC en directo" in response.answer


def test_insider_portfolio_aggregates_positions_and_declares_missing(db):
    a = company(db, "AAPL")
    b = company(db, "MSFT")
    db.add_all([
        Position(tenant_id=1, company_id=a.id, quantity=Decimal("3")),
        Position(tenant_id=1, company_id=b.id, quantity=Decimal("2")),
    ])
    insider_tx(db, "AAPL", "P", 5000.0, "2026-10-01")
    db.commit()
    response = answer_data_question(db, "¿Qué compras y ventas insider hay en mis empresas?")
    assert response is not None
    assert "posiciones abiertas" in response.answer
    assert "AAPL" in response.answer and "compró" in response.answer
    assert "Sin operaciones insider guardadas: MSFT." in response.answer
    assert response.llm_trace["path"] == "portfolio_insider"


def test_portfolio_news_dedups_same_story_with_appended_fragment(db):
    # La misma noticia guardada con el titular solo y con titular+entrada
    # pegada salía dos veces: el dedup por coincidencia exacta no las casaba.
    a = company(db, "AAPL")
    db.add(Position(tenant_id=1, company_id=a.id, quantity=1, average_cost=10, currency="USD", market_value=10, as_of=date.today()))
    db.add_all([
        NewsEvent(tenant_id=1, company_id=a.id, source="Yahoo Finance",
                  title="Apple stock is at a record high but is it warranted given slowing iPhone 18 demand?"),
        NewsEvent(tenant_id=1, company_id=a.id, source="Yahoo Finance",
                  title="Apple stock is at a record high but is it warranted given slowing iPhone 18 demand? Apple's new crop of iPhones may be falling shy of the sales mark."),
    ])
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "¿Qué noticias hay de mis empresas?", "portfolio", None))
    assert response.answer.count("Apple stock is at a record high") == 1


def test_company_quote_shows_spanish_date_and_human_source(db):
    """Visto en prod con AAPL (19-oct-2026): la prosa del chat enseñaba
    «(2026-10-18, Finnhub)» y el slug «yahoo_finance_intraday»."""
    a = company(db, "AAPL")
    db.add(MarketPrice(company_id=a.id, date=date(2026, 10, 18), close=Decimal("200"), source="yahoo_finance_intraday"))
    db.commit()
    response = answer_data_question(db, "¿Precio actual de AAPL?")
    assert response is not None
    assert "(18 oct 2026, Yahoo Finance · intradía)" in response.answer
    assert "2026-10-18" not in response.answer
    assert "yahoo_finance_intraday" not in response.answer


def test_fecha_es_tolerates_non_iso_text():
    """Objeción del auditor (19-oct-2026): un tx_date no ISO no rompe la
    respuesta; se devuelve el texto tal cual."""
    from app.services.display_es import fecha_es

    assert fecha_es(date(2026, 10, 18)) == "18 oct 2026"
    assert fecha_es("2026-10-18") == "18 oct 2026"
    assert fecha_es("finales de octubre") == "finales de octubre"



def test_portfolio_dividends_london_position_uses_gbx_records(db):
    """Dividendo Yahoo en GBX (peniques) y posicion en GBP: 0,10 GBP por accion."""
    from app.models import DividendRecord

    vod = company(db, "VOD.L")
    today = date.today()
    db.add(Position(tenant_id=1, company_id=vod.id, quantity=Decimal("100"), average_cost=Decimal("0.7"), currency="GBP", as_of=today, market_value=Decimal("70")))
    db.add(DividendRecord(tenant_id=1, company_id=vod.id, ex_date=date(today.year, 1, 15), amount=Decimal("10"), currency="GBX", source="yahoo_finance"))
    db.commit()
    response = asyncio.run(ChatService().answer(db, "¿Qué dividendos cobrará mi cartera este año?", "portfolio", None))
    assert "VOD.L: 1 pago(s)" in response.answer
    assert "Sin dividendos guardados: VOD.L" not in response.answer
