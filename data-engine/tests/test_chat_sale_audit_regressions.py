"""Synthetic audit counterexamples: chat must agree with the annual FIFO core.

No provider calls, real account, tax-rate changes, or production writes.
"""
import asyncio
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Portfolio, Position, Transaction
from app.services.chat_service import ChatService
from app.services.sale_hypothetical import parse_purchase_lots, simulate_hypothetical_sale
from app.services.sale_simulation import simulate_fifo_sale
from app.services.tax_report_service import TaxReportService

TODAY = date(2026, 10, 27)


class NoLLM:
    name = "no-llm"

    async def complete(self, *args, **kwargs):
        raise AssertionError("Sale estimates must never call a provider")


@pytest.fixture
def ledger(monkeypatch):
    class Clock(date):
        @classmethod
        def today(cls):
            return TODAY

    import app.services.chat_service as chat
    import app.services.sale_hypothetical as hypo
    monkeypatch.setattr(chat, "date", Clock)
    monkeypatch.setattr(hypo, "date", Clock)
    monkeypatch.setattr(chat, "local_today", Clock.today)
    monkeypatch.setattr(hypo, "local_today", Clock.today)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        company = Company(ticker="TEST", name="Synthetic", exchange="XETRA", currency="EUR",
                          company_type="holding", valuation_model="unassigned")
        db.add(company)
        db.flush()
        db.add(Portfolio(tenant_id=1, name="Synthetic", base_currency="EUR", is_default=True))
        yield db, company
    engine.dispose()


def buy_sell(db, company, day, action, qty, price, currency="EUR", fees="0"):
    row = Transaction(tenant_id=1, company_id=company.id, trade_date=date.fromisoformat(day),
                      action=action, quantity=D(qty), price=D(price), fees=D(fees), currency=currency)
    db.add(row)
    db.flush()
    return row


def position(db, company, qty="100", value="900", currency="EUR"):
    db.add(Position(tenant_id=1, company_id=company.id, quantity=D(qty), average_cost=D(10),
                    market_value=D(value), market_value_base=D(value), market_value_native=D(value),
                    cost_basis_base=D(qty)*10, cost_basis_native=D(qty)*10,
                    currency=currency, base_currency="EUR", as_of=TODAY))
    db.commit()


def answer(db, question):
    return asyncio.run(ChatService(provider=NoLLM()).answer(db, question, "global", None))


def test_prior_deferred_loss_enters_chat_basis_and_matches_annual(ledger):
    db, company = ledger
    for args in [("2026-07-01", "buy", "100", "10"),
                 ("2026-08-01", "sell", "100", "8"),
                 ("2026-08-10", "buy", "100", "8")]:
        buy_sell(db, company, *args)
    position(db, company)
    simulated = simulate_fifo_sale(db, tenant_id=1, company_id=company.id,
                                  quantity=D(100), held_quantity=D(100), sale_date=TODAY)
    assert simulated.cost_eur == D(1000)
    resp = answer(db, "IRPF si vendo todas las acciones de TEST")
    assert "pérdida de 100,00 €" in resp.answer
    assert "IRPF estimado" not in resp.answer
    buy_sell(db, company, "2026-10-27", "sell", "100", "9")
    annual = TaxReportService().compute_report(db, 2026, include_filing=False)
    sale = annual["realized"][0]["sales"][-1]
    assert D(str(sale["cost_base"])) == simulated.cost_eur
    assert sale["gain_base"] == -100


def test_partial_deferred_lot_preserves_remaining_basis(ledger):
    db, company = ledger
    for args in [("2025-07-01", "buy", "100", "10"),
                 ("2025-08-01", "sell", "100", "8"),
                 ("2025-08-10", "buy", "100", "8"),
                 ("2026-01-01", "sell", "40", "11")]:
        buy_sell(db, company, *args)
    position(db, company, qty="60", value="540")
    sale = simulate_fifo_sale(db, tenant_id=1, company_id=company.id,
                             quantity=D(30), held_quantity=D(60), sale_date=TODAY)
    assert sale.cost_eur == D(300)
    assert sale.blocking_qty == 0


def test_single_initial_purchase_not_repurchase(ledger):
    db, company = ledger
    buy_sell(db, company, "2026-10-01", "buy", "100", "10")
    position(db, company, value="800")
    sale = simulate_fifo_sale(db, tenant_id=1, company_id=company.id,
                             quantity=D(60), held_quantity=D(100), sale_date=TODAY)
    assert sale.blocking_qty == 0
    resp = answer(db, "IRPF si vendo 60 acciones de TEST")
    assert "pérdida de 120,00 €" in resp.answer
    assert "no se pueden compensar ahora" not in resp.answer


def test_hypothetical_previous_purchase_blocks_loss(ledger):
    db, company = ledger
    q = ("Compré 10 acciones a 10 euros el 1 de enero de 2026 y otras 10 a 8 euros "
         "el 1 de octubre de 2026, ¿qué IRPF si vendo 10 a 5 euros?")
    result = simulate_hypothetical_sale(db, lots=parse_purchase_lots(q), question=q, company=company, today=TODAY)
    assert result.gain_eur == -50
    assert result.fifo.blocking_qty == 10
    resp = ChatService()._hypothetical_sale_answer(db, q, parse_purchase_lots(q), company, "TEST")
    assert "50,00 € de la pérdida no se pueden compensar ahora" in resp.answer
    assert "la pérdida compensa otras ganancias si" not in resp.answer.lower()


def test_explicit_sale_price_wins_over_position_market_value_full_route(ledger):
    db, company = ledger
    buy_sell(db, company, "2026-01-01", "buy", "100", "10")
    position(db, company)
    resp = answer(db, "IRPF si vendo 10 acciones de TEST a 20 euros")
    assert "valor 200,00 €" in resp.answer
    assert "ganancia de 100,00 €" in resp.answer
    assert resp.llm_trace["sale_price_source"] == "usuario"


def test_explicit_foreign_price_needs_today_fx_not_position_value(ledger):
    db, company = ledger
    buy_sell(db, company, "2026-01-01", "buy", "100", "10")
    position(db, company)
    resp = answer(db, "IRPF si vendo 10 acciones de TEST a 20 dólares")
    assert "falta el tipo de cambio" in resp.answer
    assert "IRPF estimado" not in resp.answer
    db.add(FXRate(base_currency="EUR", quote_currency="USD", rate_date=TODAY, rate=D("0.9"), source="test"))
    db.commit()
    resp = answer(db, "IRPF si vendo 10 acciones de TEST a 20 dólares")
    assert "valor 180,00 €" in resp.answer
    assert "ganancia de 80,00 €" in resp.answer


@pytest.mark.parametrize("qty", ["150", "0", "-5"])
def test_saved_oversell_or_zero_never_silently_clamps(ledger, qty):
    db, company = ledger
    buy_sell(db, company, "2026-01-01", "buy", "100", "10")
    position(db, company)
    resp = answer(db, f"IRPF si vendo {qty} acciones de TEST")
    assert "Confirma la cantidad" in resp.answer
    assert "IRPF estimado" not in resp.answer


@pytest.mark.parametrize("suffix,expected", [
    ("vendo 15 a 20 euros", "no superar"),
    ("vendo 0 a 20 euros", "positiva"),
    ("vendo -5 a 20 euros", "positiva"),
    ("vendo todas a 20 euros con 50 euros de comisiones", "comisiones"),
])
def test_hypothetical_invalid_parameters_not_priced(ledger, suffix, expected):
    db, company = ledger
    q = "Compré 10 acciones a 10 euros el 1 de enero de 2026 y " + suffix
    res = simulate_hypothetical_sale(db, lots=parse_purchase_lots(q), question=q, company=company, today=TODAY)
    assert res.gain_eur is None
    assert res.tax_eur is None
    assert expected in res.invalid
    resp = ChatService()._hypothetical_sale_answer(db, q, parse_purchase_lots(q), company, "TEST")
    assert expected in resp.answer
    assert "IRPF estimado" not in resp.answer


def test_future_buy_date_rejected_even_in_euros(ledger):
    db, company = ledger
    q = "Compré 10 acciones a 10 euros el 1 de enero de 2027 y vendo todas a 20 euros"
    res = simulate_hypothetical_sale(db, lots=parse_purchase_lots(q), question=q, company=company, today=TODAY)
    assert res.gain_eur is None
    assert "futura" in res.invalid
    resp = ChatService()._hypothetical_sale_answer(db, q, parse_purchase_lots(q), company, "TEST")
    assert "futura" in resp.answer
    assert "IRPF estimado" not in resp.answer
