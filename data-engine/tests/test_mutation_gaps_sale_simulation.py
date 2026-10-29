"""Supervivientes de mutacion en ``sale_simulation`` (simulador FIFO del Cerebro, ronda 3).

Huecos que dejaban vivos los mutantes: el filtro por tenant y por empresa,
la fecha de corte de la venta, el diferido nativo por accion, las fracciones
de accion, los limites de la cantidad, la falta de tipo de cambio y las fechas
de las recompras que bloquean una perdida.
"""

from __future__ import annotations

from collections import deque
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Portfolio, Transaction
from app.services.sale_simulation import consume_fifo, repurchase_deadline, simulate_fifo_sale

RATES = {"2025-07-01": "0.80", "2025-08-01": "0.90", "2025-08-10": "0.85", "2026-01-15": "0.95"}


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        for ticker, currency in (("EURCO", "EUR"), ("USDCO", "USD"), ("OTHER", "EUR")):
            session.add(Company(ticker=ticker, name=ticker, exchange="XETRA", currency=currency,
                                company_type="holding", valuation_model="unassigned"))
        session.add(Portfolio(tenant_id=1, name="P", base_currency="EUR", is_default=True))
        for day, rate in RATES.items():
            session.add(FXRate(base_currency="EUR", quote_currency="USD",
                               rate_date=date.fromisoformat(day), rate=D(rate), source="ECB"))
        session.commit()
        yield session
    engine.dispose()


def _company(db, ticker):
    return db.query(Company).filter_by(ticker=ticker).one()


def _add(db, ticker, day, action, qty, price, *, tenant=1, currency=None):
    company = _company(db, ticker)
    db.info["tenant_id"] = tenant  # el guard de escritura exige el tenant de la sesion
    db.add(Transaction(tenant_id=tenant, company_id=company.id, trade_date=date.fromisoformat(day),
                       action=action, quantity=D(qty), price=D(price), fees=D("0"),
                       currency=currency or company.currency))
    db.commit()
    db.info["tenant_id"] = 1


def _sim(db, ticker, quantity, held, day):
    return simulate_fifo_sale(db, tenant_id=1, company_id=_company(db, ticker).id,
                              quantity=D(quantity), held_quantity=D(held), sale_date=date.fromisoformat(day))


def test_other_tenant_and_other_company_trades_never_enter_the_lots(db):
    _add(db, "EURCO", "2026-01-10", "buy", "10", "20")
    # Mismo company_id en otro tenant y otra empresa del mismo tenant: no cuentan.
    _add(db, "EURCO", "2025-06-01", "buy", "5", "1", tenant=2)
    _add(db, "OTHER", "2025-06-01", "buy", "5", "1")
    sale = _sim(db, "EURCO", "4", "10", "2026-10-27")
    assert sale is not None
    assert [(lot.trade_date, lot.quantity, lot.unit_cost_eur) for lot in sale.lots] == [
        (date(2026, 1, 10), D("4"), D("20")),
    ]
    assert sale.cost_eur == D("80")


def test_trades_after_the_sale_date_are_ignored_and_same_day_counts(db):
    _add(db, "EURCO", "2026-03-01", "buy", "10", "20")
    _add(db, "EURCO", "2026-03-05", "buy", "2", "30")  # el mismo dia de la venta: cuenta
    _add(db, "EURCO", "2026-04-01", "buy", "50", "1")  # despues: no existe aun
    sale = _sim(db, "EURCO", "12", "12", "2026-03-05")
    assert sale is not None
    assert sale.cost_eur == D("260")


def test_fractional_shares_are_lots_too(db):
    _add(db, "EURCO", "2026-03-01", "buy", "10.5", "10")
    sale = _sim(db, "EURCO", "0.5", "10.5", "2026-10-27")
    assert sale is not None
    assert sale.quantity == D("0.5")
    assert sale.cost_eur == D("5.0")


@pytest.mark.parametrize(("quantity", "held"), [("0", "10"), ("11", "10")])
def test_quantity_outside_the_position_is_not_simulated(db, quantity, held):
    _add(db, "EURCO", "2026-03-01", "buy", "10", "10")
    assert _sim(db, "EURCO", quantity, held, "2026-10-27") is None


def test_selling_exactly_one_share_is_simulated(db):
    _add(db, "EURCO", "2026-03-01", "buy", "10", "10")
    sale = _sim(db, "EURCO", "1", "10", "2026-10-27")
    assert sale is not None and sale.cost_eur == D("10")


def test_native_unit_cost_carries_the_remaining_deferred_loss(db):
    # Lote recomprado a 8 $ con 120 $ de perdida diferida restante en 60 acciones.
    for args in (("2025-07-01", "buy", "100", "10"), ("2025-08-01", "sell", "100", "8"),
                 ("2025-08-10", "buy", "100", "8"), ("2026-01-15", "sell", "40", "11")):
        _add(db, "USDCO", *args)
    sale = _sim(db, "USDCO", "30", "60", "2026-10-27")
    (lot,) = sale.lots
    assert lot.unit_cost_native == D("10")  # 8 $ + 120 $ / 60
    assert lot.currency == "USD"
    assert lot.unit_cost_eur == D("8.60")


def test_missing_purchase_fx_gives_unknown_euro_cost_not_a_crash(db):
    _add(db, "USDCO", "2026-05-05", "buy", "10", "10")  # sin tipo publicado cerca
    sale = _sim(db, "USDCO", "5", "10", "2026-10-27")
    assert sale is not None
    assert [lot.unit_cost_eur for lot in sale.lots] == [None]
    assert sale.cost_eur is None


def test_blocking_dates_list_only_window_lots_that_can_still_block(db):
    # 08-10 ya bloqueo la perdida del 08-01 (capacidad 0); 08-20 sigue libre.
    for args in (("2025-07-01", "buy", "100", "10"), ("2025-08-01", "sell", "100", "8"),
                 ("2025-08-10", "buy", "100", "8"), ("2025-08-20", "buy", "50", "8")):
        _add(db, "EURCO", *args)
    sale = _sim(db, "EURCO", "60", "150", "2025-09-15")
    assert sale.blocking_qty > 0
    assert sale.blocking_dates == [date(2025, 8, 20)]


def test_blocking_window_includes_the_purchase_exactly_two_months_before(db):
    for args in (("2026-01-10", "buy", "100", "10"), ("2026-08-27", "buy", "30", "5")):
        _add(db, "EURCO", *args)
    sale = _sim(db, "EURCO", "100", "130", "2026-10-27")
    assert sale.blocking_qty == D("30")
    assert sale.blocking_dates == [date(2026, 8, 27)]


def test_no_blocking_means_no_dates(db):
    _add(db, "EURCO", "2026-01-10", "buy", "100", "10")
    sale = _sim(db, "EURCO", "40", "100", "2026-10-27")
    assert sale.blocking_qty == 0
    assert sale.blocking_dates == []


def test_consume_fifo_crosses_lots_and_leaves_the_rest():
    lots = deque([
        {"qty": D("3"), "unit": D("10"), "unit_eur": D("9"), "date": date(2026, 1, 1), "currency": "USD"},
        {"qty": D("5"), "unit": D("20"), "unit_eur": D("18"), "date": date(2026, 2, 1), "currency": "USD"},
    ])
    sale = consume_fifo(lots, D("4"))
    assert [(lot.quantity, lot.unit_cost_native, lot.currency) for lot in sale.lots] == [
        (D("3"), D("10"), "USD"), (D("1"), D("20"), "USD"),
    ]
    assert sale.cost_eur == D("45")
    assert [lot["qty"] for lot in lots] == [D("4")]
    assert lots[0]["date"] == date(2026, 2, 1)


def test_consume_fifo_partial_first_lot_stays_in_place():
    lots = deque([{"qty": D("3"), "unit": D("10"), "unit_eur": D("9"), "date": None, "currency": "EUR"}])
    sale = consume_fifo(lots, D("0.5"))
    assert [lot.quantity for lot in sale.lots] == [D("0.5")]
    assert [lot["qty"] for lot in lots] == [D("2.5")]


def test_consume_fifo_exhausting_a_lot_of_one_share():
    lots = deque([
        {"qty": D("1"), "unit": D("10"), "unit_eur": D("10"), "date": None, "currency": "EUR"},
        {"qty": D("2"), "unit": D("11"), "unit_eur": D("11"), "date": None, "currency": "EUR"},
    ])
    sale = consume_fifo(lots, D("2"))
    assert [(lot.quantity, lot.unit_cost_native) for lot in sale.lots] == [(D("1"), D("10")), (D("1"), D("11"))]
    assert [lot["qty"] for lot in lots] == [D("1")]


@pytest.mark.parametrize(("sale_day", "deadline"), [
    ("2026-10-27", "2026-12-27"),
    ("2026-12-31", "2027-02-28"),
])
def test_repurchase_deadline_is_two_calendar_months_after(sale_day, deadline):
    assert repurchase_deadline(date.fromisoformat(sale_day)) == date.fromisoformat(deadline)


def test_a_one_share_purchase_is_a_lot(db):
    _add(db, "EURCO", "2026-01-10", "buy", "1", "30")
    _add(db, "EURCO", "2026-02-10", "buy", "2", "10")
    sale = _sim(db, "EURCO", "3", "3", "2026-10-27")
    assert sale is not None
    assert [(lot.quantity, lot.unit_cost_eur) for lot in sale.lots] == [(D("1"), D("30")), (D("2"), D("10"))]


def test_rows_without_action_or_quantity_are_not_legs(db):
    _add(db, "EURCO", "2026-01-10", "buy", "4", "25")
    _add(db, "EURCO", "2026-01-11", "dividend", "1", "3")
    _add(db, "EURCO", "2026-01-12", "buy", "0", "99")
    sale = _sim(db, "EURCO", "4", "4", "2026-10-27")
    assert sale is not None
    assert sale.cost_eur == D("100")


def test_an_earlier_full_sale_makes_the_window_buy_the_initial_purchase(db):
    # Vendido todo antes de la ventana: la unica compra dentro de la ventana es
    # la compra inicial (excepcion del Manual), no una recompra que bloquee.
    _add(db, "EURCO", "2025-01-02", "buy", "10", "20")
    _add(db, "EURCO", "2025-02-03", "sell", "10", "22")
    _add(db, "EURCO", "2026-03-02", "buy", "10", "20")
    sale = _sim(db, "EURCO", "5", "10", "2026-04-01")
    assert sale is not None
    assert not sale.blocking_qty
    assert sale.blocking_dates == []
