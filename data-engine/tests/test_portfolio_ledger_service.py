"""PortfolioLedgerService.rebuild_position contract tests.

The ledger is the canonical record; positions are derived. Average-cost
accounting must be exact, invalid ledgers must fail loudly, and base
currency fields must stay None - never guessed - when FX history is
incomplete.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Position
from app.services.portfolio_ledger_service import PortfolioLedgerService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _buy(service, db, **overrides):
    args = {
        "ticker": "AAPL", "action": "buy", "quantity": Decimal("10"),
        "price": Decimal("100"), "trade_date": date(2026, 1, 10), "currency": "EUR",
    }
    args.update(overrides)
    return service.create_transaction(db, **args)


def test_average_cost_and_realized_pnl_from_ledger(db):
    service = PortfolioLedgerService()
    _buy(service, db)                                                     # 10 @ 100
    _buy(service, db, quantity=Decimal("10"), price=Decimal("120"),
         trade_date=date(2026, 2, 10))                                    # 10 @ 120
    _buy(service, db, action="sell", quantity=Decimal("5"),
         price=Decimal("150"), trade_date=date(2026, 3, 10))
    company = service.ensure_company(db, "AAPL")

    position = service.rebuild_position(db, company.id)
    assert position is not None
    assert position.quantity == Decimal("15")
    # Average cost after two buys: (1000+1200)/20 = 110; sell 5 @ 150 -> +200 realized.
    assert position.average_cost == Decimal("110")
    assert position.realized_pnl == Decimal("200")
    assert position.cost_basis_native == Decimal("1650")
    # No quote was ever stored: the 100 kept by earlier rebuilds is only the
    # first trade's provisional price, so the last trade (sell @ 150) values it.
    # A real stored quote still wins (test_ledger_rebuild_quote_date_f366).
    assert position.market_price == Decimal("150")
    assert position.currency == "EUR"
    assert position.source == "postgres_ledger"
    # Same-currency ledger in EUR base: base fields fully populated.
    assert position.cost_basis_base == Decimal("1650")
    assert position.unrealized_pnl_base is not None


def test_oversell_fails_loudly_at_write_time(db):
    service = PortfolioLedgerService()
    _buy(service, db)
    # create_transaction rebuilds the position eagerly: invalid ledgers are
    # rejected when the transaction is written, not later.
    with pytest.raises(ValueError, match="Cannot sell"):
        _buy(service, db, action="sell", quantity=Decimal("11"),
             trade_date=date(2026, 2, 10))


def test_mixed_currency_ledger_rejected_at_write_time(db):
    service = PortfolioLedgerService()
    _buy(service, db)
    with pytest.raises(ValueError, match="cannot mix transaction currencies"):
        _buy(service, db, currency="USD", trade_date=date(2026, 2, 10))


def test_full_sell_removes_position(db):
    service = PortfolioLedgerService()
    _buy(service, db)
    _buy(service, db, action="sell", quantity=Decimal("10"),
         price=Decimal("150"), trade_date=date(2026, 2, 10))
    company = service.ensure_company(db, "AAPL")
    assert service.rebuild_position(db, company.id) is None
    assert db.scalar(select(Position).where(Position.company_id == company.id)) is None


def test_missing_fx_history_leaves_base_fields_none(db):
    service = PortfolioLedgerService()
    # USD ledger with no stored USD->EUR rates at all.
    _buy(service, db, currency="USD")
    company = service.ensure_company(db, "AAPL")
    position = service.rebuild_position(db, company.id)
    assert position.quantity == Decimal("10")
    assert position.average_cost == Decimal("100")  # native accounting unaffected
    assert position.market_value_base is None
    assert position.cost_basis_base is None
    assert position.unrealized_pnl_base is None
    assert position.realized_pnl_base is None


def test_rebuild_position_uses_last_transaction_date_by_default(db):
    service = PortfolioLedgerService()
    _buy(service, db, trade_date=date(2026, 1, 10))
    company = service.ensure_company(db, "AAPL")

    position = service.rebuild_position(db, company.id)

    assert position is not None
    assert position.as_of == date(2026, 1, 10)


def _rates(service, monkeypatch, table):
    """EUR por USD por fecha; una fecha ausente = sin tipo de cambio ese dia."""
    monkeypatch.setattr(
        service.fx, "rate",
        lambda db, *, quote_currency, base_currency, as_of: (
            Decimal("1") if quote_currency == base_currency else table.get(as_of)
        ),
    )


def test_sell_without_fx_keeps_the_remaining_cost_base(db, monkeypatch):
    service = PortfolioLedgerService()
    d1, d2 = date(2026, 1, 10), date(2026, 2, 10)
    _rates(service, monkeypatch, {d1: Decimal("0.9")})
    _buy(service, db, currency="USD", trade_date=d1)          # 10 @ 100 USD -> 900 EUR
    _buy(service, db, currency="USD", action="sell", quantity=Decimal("4"),
         price=Decimal("120"), trade_date=d2)                 # sin FX ese dia
    position = service.rebuild_position(db, service.ensure_company(db, "AAPL").id)
    assert position.quantity == Decimal("6")
    # Coste base de las 6 restantes: 900 * 6/10 = 540 EUR, sin depender del FX de la venta.
    assert position.cost_basis_base == Decimal("540")
    assert position.realized_pnl_base is None                 # este si necesita el FX


def test_missing_fx_in_a_closed_lot_does_not_blank_the_new_lot(db, monkeypatch):
    service = PortfolioLedgerService()
    d1, d2, d3 = date(2025, 1, 10), date(2025, 2, 10), date(2026, 1, 10)
    _rates(service, monkeypatch, {d3: Decimal("0.9")})
    _buy(service, db, currency="USD", trade_date=d1)
    _buy(service, db, currency="USD", action="sell", quantity=Decimal("10"),
         price=Decimal("110"), trade_date=d2)
    _buy(service, db, currency="USD", quantity=Decimal("5"), price=Decimal("200"),
         trade_date=d3)                                       # nuevo lote con FX
    position = service.rebuild_position(db, service.ensure_company(db, "AAPL").id)
    assert position.average_cost == Decimal("200")
    assert position.cost_basis_base == Decimal("900")         # 5 * 200 * 0.9
    assert position.market_value_base == Decimal("900")
    assert position.unrealized_pnl_base == Decimal("0")
    assert position.realized_pnl == Decimal("100")            # nativo: (110-100)*10
    assert position.realized_pnl_base is None                 # lote cerrado sin FX
