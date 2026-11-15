"""Herramientas en vivo del Cerebro: cotización y noticias pedidas al proveedor.

Los tests nunca salen a red: el ExtendedQuoteService y el GDELTClient se
sustituyen por dobles. Lo que se verifica es el contrato fail-closed (un
proveedor caído devuelve la pregunta a la ruta de datos guardados), la
etiqueta de fuente + marca temporal y que un cierre fechado nunca se
presenta como cotización en directo.
"""
import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice
from app.models.entities import Base
from app.schemas import ChatPageContext
from app.services.brain_live_tools import answer_live_question
from app.services.chat_service import ChatService
from app.services.extended_quote_service import ExtendedQuote


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


@pytest.fixture(autouse=True)
def _allow_live_calls(monkeypatch):
    """APP_ENV=test no sale a red: estos tests activan la guarda y doblan el proveedor."""
    from app.services import brain_live_tools

    monkeypatch.setattr(brain_live_tools, "_live_calls_allowed", lambda: True)


@pytest.fixture(autouse=True)
def _no_live_dividend_sync(monkeypatch):
    """Los tests nunca llaman al proveedor: sin datos propios responde «no tengo»."""
    from app.services.dividend_ingestion_service import DividendIngestionService

    async def unavailable(self, db_, *, ticker):
        return {"ticker": ticker, "status": "unavailable", "inserted": 0, "existing": 0}

    monkeypatch.setattr(DividendIngestionService, "sync_company", unavailable)


def company(db, ticker, name=None):
    row = Company(ticker=ticker, name=name or ticker + " Inc", currency="USD",
                  exchange="NASDAQ", company_type="operating", valuation_model="unassigned")
    db.add(row)
    db.flush()
    return row


def live_quote(ticker, price, *, session="regular", status="available",
               timestamp=1_800_000_000, change_percent=1.25):
    return ExtendedQuote(
        ticker=ticker, status=status, session=session, price_session=session,
        price=price, timestamp=timestamp, currency="USD",
        fetched_at=timestamp, trading_date="2027-01-15",
        change_percent=change_percent if session != "cerrado" else None,
    )


def unavailable_quote(ticker):
    return ExtendedQuote(ticker=ticker, fetched_at=1_800_000_000)


def patch_quotes(monkeypatch, quotes: dict[str, ExtendedQuote]):
    from app.services.extended_quote_service import extended_quote_service

    async def fake_get(ticker: str) -> ExtendedQuote:
        return quotes.get(ticker.strip().upper(), unavailable_quote(ticker))

    monkeypatch.setattr(extended_quote_service, "get", fake_get)


def patch_news(monkeypatch, payload=None, error: Exception | None = None):
    from app.services.connectors.gdelt import GDELTClient

    async def fake_search(self, query: str, max_records: int = 50) -> dict:
        if error is not None:
            raise error
        return payload if payload is not None else {"articles": []}

    monkeypatch.setattr(GDELTClient, "news_search", fake_search)


def test_live_quote_dated_sourced_without_llm(db, monkeypatch):
    company(db, "ASTS", "AST SpaceMobile")
    patch_quotes(monkeypatch, {"ASTS": live_quote("ASTS", 105.30)})
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "¿A cuánto está ASTS?", "portfolio", None))
    assert "$105.30" in response.answer
    assert "+1,25 %" in response.answer
    assert "mercado abierto" in response.answer
    assert "Yahoo Finance" in response.answer
    # Marca temporal siempre visible: nunca una cifra «actual» sin su fecha.
    assert "ene 2027" in response.answer
    assert response.llm_trace["provider_calls"] == 0
    assert response.llm_trace["path"] == "live_quote"
    assert response.prompt_version == "brain-live-v1"
    assert all(source["url"].startswith("https://finance.yahoo.com/quote/") for source in response.sources)


def test_closed_market_is_dated_close_never_live(db, monkeypatch):
    company(db, "AAPL")
    patch_quotes(monkeypatch, {"AAPL": live_quote("AAPL", 250.0, session="cerrado")})
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "precio de AAPL", "portfolio", None))
    assert "$250.00" in response.answer
    assert "al cierre" in response.answer
    assert "Mercado cerrado" in response.answer
    assert "en directo" not in response.answer.lower()


def test_provider_down_falls_back_to_stored_answer(db, monkeypatch):
    a = company(db, "AAPL")
    db.add(MarketPrice(company_id=a.id, date=date.today(), close=Decimal("200"), source="yahoo"))
    patch_quotes(monkeypatch, {})  # todo unavailable
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "¿Precio de AAPL?", "portfolio", None))
    # Fail-closed: sin dato en vivo responde la ruta guardada, etiquetada.
    assert "Último precio almacenado: $200.00" in response.answer
    assert "no es una cotización en directo" in response.answer.lower()
    assert response.llm_trace["path"] == "company_quote"


def test_quote_timeout_is_fail_closed(db, monkeypatch):
    company(db, "AAPL")
    from app.services.extended_quote_service import extended_quote_service

    async def slow_get(ticker: str) -> ExtendedQuote:
        await asyncio.sleep(30)
        return live_quote(ticker, 1.0)

    monkeypatch.setattr(extended_quote_service, "get", slow_get)
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "precio de AAPL", "portfolio", None))
    assert response.llm_trace["path"] != "live_quote"
    assert "Yahoo" not in response.answer


def test_multi_ticker_live_quotes_and_partial_failure(db, monkeypatch):
    company(db, "AAPL")
    company(db, "MSFT")
    patch_quotes(monkeypatch, {"AAPL": live_quote("AAPL", 250.0)})
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "precio de AAPL y MSFT", "portfolio", None))
    assert response.llm_trace["path"] == "live_quote"
    assert "$250.00" in response.answer
    assert "MSFT" in response.answer
    assert "sin cotización en directo" in response.answer
    # La empresa sin dato no lleva fuente en vivo: nunca se enlaza lo que no se consultó.
    assert all("AAPL" in source["title"] for source in response.sources)


def test_purchase_cost_and_valuation_are_not_hijacked(db, monkeypatch):
    company(db, "AAPL")
    patch_quotes(monkeypatch, {"AAPL": live_quote("AAPL", 250.0)})
    for question in ("¿a cuánto compré AAPL?", "precio objetivo de AAPL",
                     "¿Precio actual de AAPL y su PER?",
                     "¿Cuál es el margen FCF de AAPL y cuál es su precio actual?"):
        response = asyncio.run(ChatService().answer(db, question, "portfolio", None))
        assert response.llm_trace.get("path") != "live_quote", question


def test_live_calls_disabled_in_test_env_by_default(db, monkeypatch):
    """Sin la guarda levantada, APP_ENV=test nunca sale a red: devuelve None."""
    monkeypatch.undo()  # recupera la guarda real (la fixture autouse la sustituye)
    from app.services.brain_live_tools import _live_calls_allowed

    assert _live_calls_allowed() is False


def test_page_context_company_used_when_question_has_none(db, monkeypatch):
    company(db, "ASTS", "AST SpaceMobile")
    patch_quotes(monkeypatch, {"ASTS": live_quote("ASTS", 105.30)})
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    page = ChatPageContext(path="/research/ASTS", label="ASTS", ticker="ASTS")
    response = asyncio.run(ChatService().answer(db, "¿a cuánto está?", "portfolio", None, page=page))
    assert response.llm_trace["path"] == "live_quote"
    assert "$105.30" in response.answer


def test_live_news_relevant_dated_and_sourced(db, monkeypatch):
    company(db, "ASTS", "AST SpaceMobile")
    patch_news(monkeypatch, {"articles": [
        {"title": "AST SpaceMobile launches BlueBird 7", "url": "https://example.com/a",
         "seendate": "20270115T100000Z", "domain": "example.com", "language": "english"},
        {"title": "ASTS firma acuerdo con Vodafone", "url": "https://example.es/b",
         "seendate": "20270114T090000Z", "domain": "example.es", "language": "spanish"},
        # Sin fecha: se etiqueta, no se inventa.
        {"title": "AST SpaceMobile raises guidance", "url": "https://example.com/c",
         "domain": "example.com", "language": "english"},
        # Otra empresa: la relevancia fail-closed la descarta.
        {"title": "Vodafone sube un 2 % en bolsa", "url": "https://example.com/d",
         "seendate": "20270115T110000Z", "domain": "example.com", "language": "english"},
        # Idioma no legible: fuera (misma regla que la ingesta).
        {"title": "AST SpaceMobile 衛星", "url": "https://example.jp/e",
         "seendate": "20270115T120000Z", "domain": "example.jp", "language": "japanese"},
        # Duplicado exacto: una sola vez.
        {"title": "AST SpaceMobile launches BlueBird 7", "url": "https://example.com/a2",
         "seendate": "20270115T103000Z", "domain": "example.com", "language": "english"},
    ]})
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "últimas noticias de ASTS", "portfolio", None))
    assert response.llm_trace["path"] == "live_news"
    assert response.llm_trace["provider_calls"] == 0
    assert "BlueBird 7" in response.answer
    assert "Vodafone sube" not in response.answer
    assert "衛星" not in response.answer
    assert response.answer.count("BlueBird 7") == 1
    assert "sin fecha" in response.answer
    assert "GDELT" in response.answer
    assert {source["url"] for source in response.sources} == {
        "https://example.com/a", "https://example.es/b", "https://example.com/c"}


def test_news_rate_limited_falls_back_to_stored(db, monkeypatch):
    from app.services.connectors.gdelt import GdeltRateLimited

    company(db, "ASTS", "AST SpaceMobile")
    patch_news(monkeypatch, error=GdeltRateLimited(60.0))
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(ChatService().answer(db, "últimas noticias de ASTS", "portfolio", None))
    assert response.llm_trace.get("path") != "live_news"


def test_news_without_relevant_articles_returns_none(db, monkeypatch):
    a = company(db, "ASTS", "AST SpaceMobile")
    patch_news(monkeypatch, {"articles": [
        {"title": "Mercados al alza en Europa", "url": "https://example.com/x",
         "seendate": "20270115T100000Z", "domain": "example.com", "language": "spanish"},
    ]})
    assert asyncio.run(answer_live_question(db, "últimas noticias de ASTS")) is None
    # Y sin artículos verificables (payload roto) también.
    patch_news(monkeypatch, {"articles": "no-es-lista"})
    assert asyncio.run(answer_live_question(db, "últimas noticias de ASTS")) is None
    patch_news(monkeypatch, error=ValueError("JSON roto"))
    assert asyncio.run(answer_live_question(db, "últimas noticias de ASTS")) is None
    assert a.ticker == "ASTS"


def test_no_company_no_live_answer(db, monkeypatch):
    patch_quotes(monkeypatch, {"AAPL": live_quote("AAPL", 250.0)})
    assert asyncio.run(answer_live_question(db, "¿a cuánto está el oro?")) is None
    assert asyncio.run(answer_live_question(db, "")) is None
    assert asyncio.run(answer_live_question(db, "¿qué tesis tengo?")) is None


def test_portfolio_news_route_not_hijacked(db, monkeypatch):
    company(db, "AAPL")
    patch_news(monkeypatch, {"articles": [
        {"title": "AAPL sube", "url": "https://example.com/a", "language": "spanish"},
    ]})
    assert asyncio.run(answer_live_question(db, "noticias de mi cartera")) is None
    assert asyncio.run(answer_live_question(db, "vende AAPL y dime noticias")) is None


def test_price_and_news_together_answer_both(db, monkeypatch):
    company(db, "ASTS", "AST SpaceMobile")
    patch_quotes(monkeypatch, {"ASTS": live_quote("ASTS", 105.30)})
    patch_news(monkeypatch, {"articles": [
        {"title": "AST SpaceMobile launches BlueBird 7", "url": "https://example.com/a",
         "seendate": "20270115T100000Z", "domain": "example.com", "language": "english"},
    ]})
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    response = asyncio.run(
        ChatService().answer(db, "precio y noticias de ASTS", "portfolio", None))
    assert response.llm_trace["path"] == "live_quote+live_news"
    assert "$105.30" in response.answer
    assert "BlueBird 7" in response.answer
    assert len(response.sources) == 2


def test_english_live_quote_copy(db, monkeypatch):
    from types import SimpleNamespace

    from app.core import i18n

    monkeypatch.setattr(i18n, "get_settings", lambda: SimpleNamespace(i18n_generation_enabled=True))
    company(db, "AAPL")
    patch_quotes(monkeypatch, {"AAPL": live_quote("AAPL", 250.0, session="post")})
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    db.info["language"] = "en"
    response = asyncio.run(ChatService().answer(db, "price of AAPL", "portfolio", None))
    assert response.llm_trace["path"] == "live_quote"
    assert "post-market" in response.answer
    assert "+1.25 %" in response.answer


def test_closed_postmarket_is_not_regular_close(db, monkeypatch):
    company(db, "AAPL")
    quote = live_quote("AAPL", 250.0, session="cerrado")
    quote.price_session = "post"
    patch_quotes(monkeypatch, {"AAPL": quote})
    response = asyncio.run(answer_live_question(db, "precio AAPL"))
    assert response is not None
    assert "post-mercado" in response.answer
    assert "al cierre" not in response.answer


@pytest.mark.parametrize("quote_available,news_available", [(True, False), (False, True)])
def test_mixed_request_does_not_drop_failed_half(db, monkeypatch, quote_available, news_available):
    company(db, "ASTS", "AST SpaceMobile")
    patch_quotes(monkeypatch, {"ASTS": live_quote("ASTS", 105.3)} if quote_available else {})
    patch_news(monkeypatch, {"articles": [
        {"title": "ASTS signs deal", "url": "https://example.com/a", "language": "english"}
    ] if news_available else []})
    assert asyncio.run(answer_live_question(db, "precio y noticias ASTS")) is None


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,test", "https://", "https://u:p@example.com/a", "https://[invalid"])
def test_news_rejects_unsafe_source_urls(db, monkeypatch, url):
    company(db, "ASTS", "AST SpaceMobile")
    patch_news(monkeypatch, {"articles": [{"title": "ASTS signs deal", "url": url, "language": "english"}]})
    assert asyncio.run(answer_live_question(db, "noticias ASTS")) is None


def test_unknown_explicit_ticker_does_not_use_page_company(db, monkeypatch):
    a = company(db, "AAPL")
    patch_quotes(monkeypatch, {"AAPL": live_quote("AAPL", 250.0)})
    assert asyncio.run(answer_live_question(db, "precio ZZZZZ", page_company=a)) is None


def test_news_malformed_fields_fail_closed(db, monkeypatch):
    company(db, "ASTS", "AST SpaceMobile")
    patch_news(monkeypatch, {"articles": [
        None, {"title": {"unexpected": "ASTS"}, "url": "https://example.com/a"},
        {"title": "ASTS valid", "url": ["https://example.com/a"]},
        {"title": "ASTS valid", "url": "https://example.com/a", "seendate": 1234, "domain": {"bad": "value"}},
    ]})
    response = asyncio.run(answer_live_question(db, "noticias ASTS"))
    assert response is not None
    assert "sin fecha" in response.answer
    assert len(response.sources) == 1


@pytest.mark.parametrize("tickers,question", [
    (["ASTS"], "Precio de ASTS y ZZZZZ ahora"),
    (["ASTS", "AAPL", "MSFT", "META", "AMZN"], "Precio de ASTS AAPL MSFT META AMZN ahora"),
])
def test_incomplete_company_coverage_falls_back_before_network(db, monkeypatch, tickers, question):
    from app.services import brain_live_tools

    for ticker in tickers:
        company(db, ticker)

    async def unexpected_network(*args, **kwargs):
        pytest.fail("incomplete company coverage must fall back before network")

    monkeypatch.setattr(brain_live_tools, "_live_quote_answer", unexpected_network)
    monkeypatch.setattr(brain_live_tools, "_live_news_answer", unexpected_network)
    assert asyncio.run(answer_live_question(db, question)) is None


def test_repeated_ticker_does_not_exhaust_company_limit(db, monkeypatch):
    company(db, "ASTS")
    patch_quotes(monkeypatch, {"ASTS": live_quote("ASTS", 105.3)})
    response = asyncio.run(answer_live_question(db, "precio ASTS ASTS ASTS ASTS ASTS"))
    assert response is not None
    assert len(response.sources) == 1
