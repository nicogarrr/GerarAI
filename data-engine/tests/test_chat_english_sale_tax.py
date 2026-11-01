"""Chat en inglés (Ajustes → Idioma = English): IRPF de una venta.

Con el inglés elegido, «How much tax would I pay if I sell 10 UBER?» acababa
en «No ejecuto órdenes…» (por «sell») y nunca llegaba a la simulación FIFO con
tu posición. Ahora la misma simulación responde en inglés. En español nada
cambia.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, Position, Transaction
from app.services.chat_service import ChatService, _sale_question_es


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _session(language: str):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    session.info["language"] = language
    companies = {}
    for ticker in ("UBER", "ASTS", "MSFT", "KO"):
        comp = Company(ticker=ticker, name=f"{ticker} Inc", exchange="NYSE", company_type="platform",
                       valuation_model="unassigned", currency="EUR")
        session.add(comp)
        session.flush()
        companies[ticker] = comp
    session.add(Transaction(tenant_id=1, company_id=companies["UBER"].id, trade_date=date(2024, 3, 1),
                            action="buy", quantity=Decimal(40), price=Decimal(50), fees=Decimal(0), currency="EUR"))
    session.add(Transaction(tenant_id=1, company_id=companies["UBER"].id, trade_date=date(2025, 6, 1),
                            action="sell", quantity=Decimal(10), price=Decimal(80), fees=Decimal(0), currency="EUR"))
    for ticker, qty, cost, value in (("UBER", 30, 1500, 2400), ("ASTS", 100, 1200, 900), ("MSFT", 5, 1200, 1800)):
        session.add(Position(
            tenant_id=1, company_id=companies[ticker].id, quantity=Decimal(qty), average_cost=Decimal(cost) / qty,
            market_value=Decimal(value), market_value_native=Decimal(value), market_value_base=Decimal(value),
            cost_basis_native=Decimal(cost), cost_basis_base=Decimal(cost),
            currency="EUR", base_currency="EUR", as_of=date(2026, 10, 30),
        ))
    session.commit()
    return session


@pytest.fixture
def en():
    session = _session("en")
    yield session
    session.close()


@pytest.fixture
def es():
    session = _session("es")
    yield session
    session.close()


def _ask(db, question):
    return asyncio.run(ChatService().answer(db, question, "portfolio", None))


def test_sale_tax_with_fifo_in_english(en):
    resp = _ask(en, "How much tax would I pay if I sell 10 UBER?")
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert resp.answer.startswith(
        "If you sold 10 of your 30 UBER shares today (data as of Oct 30, 2026): "
        "value 800.00 €, cost 500.00 €, a gain of 300.00 €. Estimated IRPF (Spanish income tax): 57.00 € (19% of the gain, "
    )
    assert "FIFO method, required for IRPF (art. 37.2 LIRPF): the oldest shares are sold first. " \
           "Lots sold: Mar 1, 2024, 10 shares, cost 500.00 €." in resp.answer
    assert resp.answer.endswith("It's an estimate, not tax advice; the details are in Taxes.")
    assert resp.sources[0]["title"] == "Position UBER"


@pytest.mark.parametrize(("question", "start"), [
    ("How much tax would I pay if I sell all my UBER?", "If you sold all your 30 UBER shares today"),
    ("What would my capital gains tax be if I sold half my UBER?", "If you sold 15 of your 30 UBER shares today"),
    ("How much would I gain if I sell UBER?", "If you sold all your 30 UBER shares today"),
    ("How much tax would I pay if I sell 10 UBER at 90 €?",
     "If you sold 10 of your 30 UBER shares today (data as of Oct 30, 2026): value 900.00 €, cost 500.00 € "
     "(sale price given: 90.00 €), a gain of 400.00 €."),
])
def test_sale_phrasings_in_english(en, question, start):
    resp = _ask(en, question)
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert resp.answer.startswith(start)


def test_loss_and_average_cost_in_english(en):
    resp = _ask(en, "How much tax would I pay if I sell ASTS?")
    assert resp.answer.startswith(
        "If you sold all your 100 ASTS shares today (data as of Oct 30, 2026): value 900.00 €, cost 1,200.00 €, "
        "a loss of 300.00 €. You wouldn't pay IRPF on this sale. The loss offsets other gains this year, "
        "as long as you don't buy ASTS back before "
    )
    assert "Note: there is no lot history, so this estimate uses the average cost" in resp.answer


@pytest.mark.parametrize(("question", "expected"), [
    ("How much tax would I pay if I sell 0 UBER?",
     "To estimate the IRPF (Spanish income tax) on a sale, the quantity has to be greater than 0: "
     "you hold 30 UBER shares. Confirm the quantity; I haven't calculated any sale."),
    ("How much tax would I pay if I sell 50 UBER?",
     "You're asking to sell 50 UBER shares, but you hold 30. Confirm the quantity; "
     "I haven't calculated a different sale."),
    ("How much tax would I pay if I sell KO?",
     "You don't hold KO in your portfolio, so I can't calculate your real IRPF (Spanish income tax) on a sale. "
     "Add your purchases in Portfolio and ask me again."),
    ("Sell 10 UBER",
     "I don't place orders: GerarAI doesn't buy or sell at your broker. I can show you what I have saved for "
     "UBER (price, figures, thesis and news, with their sources) or your position in the portfolio."),
])
def test_sale_clarifications_in_english(en, question, expected):
    assert _ask(en, question).answer == expected


def test_several_tickers_in_english(en):
    resp = _ask(en, "How much tax would I pay if I sell UBER and MSFT?")
    assert resp.answer.startswith("I calculate the IRPF of selling one stock at a time and you named UBER and MSFT.")


def test_spanish_unchanged(es):
    resp = _ask(es, "¿Cuánto IRPF pagaría si vendo 10 UBER?")
    assert resp.answer.startswith(
        "Si vendieras hoy 10 de tus 30 acciones de UBER (datos a 30 oct 2026): "
        "valor 800,00 €, coste 500,00 €, ganancia de 300,00 €. IRPF estimado: 57,00 €"
    )
    assert resp.answer.endswith("Es una estimación, no asesoría fiscal; el detalle está en Fiscal.")
    assert _ask(es, "vendo 10 UBER").answer.startswith("No ejecuto órdenes")
    # La frase en inglés sin el inglés elegido sigue su ruta de siempre.
    assert _ask(es, "How much tax would I pay if I sell 10 UBER?").llm_trace["path"] == "order_verb"


def test_sale_question_parsing():
    assert _sale_question_es("if I sell 10 UBER at $80") == "if I vendo 10 UBER a $80"
    assert _sale_question_es("if I sell half my UBER") == "if I vendo la mitad my UBER"
    assert _sale_question_es("if I sold all my UBER") == "if I vendo mis UBER"
    assert _sale_question_es("if I sell 50 percent of UBER") == "if I vendo 50 % of UBER"
