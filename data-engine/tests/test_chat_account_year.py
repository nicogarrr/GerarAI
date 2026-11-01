"""Chat: «¿cuánto he ganado este año?» y «¿qué he vendido este año?».

Antes, «¿cuánto he ganado este año?» daba solo la rentabilidad latente de las
posiciones abiertas (sin año) y «¿qué he vendido este año?» no tenía respuesta.
Ahora el chat separa lo REALIZADO en el ejercicio (ventas, del mismo cálculo
FIFO del informe fiscal), los dividendos cobrados y lo LATENTE de lo que
sigue abierto, con etiquetas claras y sin sumarlos. Solo lectura, solo tus
datos; «este año» es el año de Madrid (local_today()).
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, FXRate, Position, Transaction
from app.services import brain_account_tools
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las ganancias del año no deben pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    cos = {}
    for ticker in ("UBER", "MSFT", "KO", "AAPL"):
        c = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                    valuation_model="unassigned", currency="USD")
        db.add(c)
        db.flush()
        cos[ticker] = c

    def tx(tenant, ticker, day, action, qty, price, fees="0"):
        db.add(Transaction(tenant_id=tenant, company_id=cos[ticker].id, trade_date=day, action=action,
                           quantity=Decimal(qty), price=Decimal(price), fees=Decimal(fees), currency="USD"))

    for tenant in (1, 2):
        db.info["tenant_id"] = tenant
        d = date(2021, 12, 1)
        while d <= date(2026, 11, 1):
            db.add(FXRate(tenant_id=tenant, base_currency="EUR", quote_currency="USD", rate=Decimal("0.9"),
                          rate_date=d, source="ecb"))
            d += timedelta(days=1)
        if tenant == 1:
            tx(1, "UBER", date(2024, 3, 1), "buy", 40, "50", "1")
            tx(1, "UBER", date(2025, 6, 1), "sell", 10, "80", "1")
            tx(1, "MSFT", date(2023, 1, 5), "buy", 5, "240")
            tx(1, "MSFT", date(2026, 3, 10), "dividend", 1, "4.15")
            tx(1, "MSFT", date(2026, 3, 10), "withholding", 1, "0.62")
            tx(1, "KO", date(2022, 1, 5), "buy", 20, "60")
            tx(1, "KO", date(2026, 10, 1), "sell", 20, "70")
            for ticker, q, v, c in (("UBER", 30, "2400", "1500"), ("MSFT", 5, "1800", "1200")):
                db.add(Position(tenant_id=1, company_id=cos[ticker].id, quantity=Decimal(q),
                                average_cost=Decimal(c) / q, market_value=Decimal(v), market_value_native=Decimal(v),
                                market_value_base=Decimal(v), cost_basis_native=Decimal(c),
                                cost_basis_base=Decimal(c), currency="EUR", base_currency="EUR",
                                as_of=date(2026, 10, 30)))
        else:
            tx(2, "AAPL", date(2020, 1, 5), "buy", 100, "70")
            tx(2, "AAPL", date(2026, 5, 4), "sell", 100, "170")
        db.commit()
    db.info["tenant_id"] = 1
    return db


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 10, 30))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", [
    "¿Cuánto he ganado este año?",
    "¿cuánto llevo ganado en lo que va de año?",
    "¿Cuánto he ganado en 2026?",
])
def test_gains_this_year_split_realized_dividends_and_unrealized(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_year_gains"
    text = resp.answer
    assert text.startswith("En 2026 (hasta el 30 oct 2026):")
    assert "Realizado con ventas: +180,00 € (1 venta: KO)" in text
    assert "Dividendos cobrados: 3,74 € brutos, 0,56 € de retención en origen" in text
    assert "Latente (lo que sigue abierto, no vendido): +1.500,00 € (+55,6 %) sobre un coste de 2.700,00 €" in text
    assert "No se suman" in text
    assert "AAPL" not in text and "9.000" not in text


def test_gains_past_year_stays_with_the_tax_block():
    # Un ejercicio pasado lo sigue respondiendo el bloque fiscal (#3952).
    resp = _ask(_db(), "¿Cuánto he ganado en 2025?")
    assert resp.llm_trace["path"] == "personal_context"
    assert "Ejercicio 2025" in resp.answer


def test_what_did_i_sell_this_year():
    resp = _ask(_db(), "¿Qué he vendido este año?")
    assert resp.llm_trace["path"] == "account_sales"
    assert "En 2026 vendiste:" in resp.answer
    assert "- KO: 20 acciones el 1 oct 2026, por 1.260,00 €; ganancia +180,00 €" in resp.answer
    assert "Total realizado: +180,00 €" in resp.answer
    assert "AAPL" not in resp.answer


@pytest.mark.parametrize("question", ["¿Qué vendí en 2025?", "mis ventas de 2025"])
def test_sales_of_a_past_year(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_sales"
    assert "- UBER: 10 acciones el 1 jun 2025" in resp.answer


def test_no_sales_in_year():
    resp = _ask(_db(), "¿Qué vendí en 2023?")
    assert resp.llm_trace["path"] == "account_sales"
    assert resp.answer.startswith("En 2023 no hay ventas en tus operaciones guardadas.")


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Qué he vendido este año?")
    assert "AAPL" in resp.answer and "KO" not in resp.answer
    resp = _ask(db, "¿Cuánto he ganado este año?")
    assert "Realizado con ventas: +9.000,00 € (1 venta: AAPL)" in resp.answer
    assert "KO" not in resp.answer and "1.500,00" not in resp.answer and "Latente" not in resp.answer
    db.info["tenant_id"] = 3
    resp = _ask(db, "¿Qué he vendido este año?")
    assert "no hay ventas" in resp.answer and "AAPL" not in resp.answer and "KO" not in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, "How much have I made this year?")
    assert resp.llm_trace["path"] == "account_year_gains"
    assert resp.answer.startswith("In 2026 (to Oct 30, 2026):")
    assert "Realized from sales: +180.00 € (1 sale: KO)" in resp.answer
    resp = _ask(db, "What did I sell this year?")
    assert resp.llm_trace["path"] == "account_sales"
    assert "- KO: 20 shares on Oct 1, 2026, for 1,260.00 €; gain +180.00 €" in resp.answer


@pytest.mark.parametrize("question", [
    "¿Cuánto he ganado en total?",
    "¿Cuánto he ganado con UBER este año?",
    "¿Cuánto ganaría si vendo UBER?",
])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") not in {"account_year_gains", "account_sales"}
