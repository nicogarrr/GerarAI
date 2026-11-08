"""Inicio de la tenencia actual por posicion (app/services/holding_period.py).

Hueco de cobertura: el modulo no tenia ningun test. El «Desde» de una
posicion no es la primera compra registrada: si se vendio entera y se volvio
a comprar, la tenencia actual empieza en la compra que la reabrio. Se
reproduce el ledger compra/venta en orden (fecha, created_at, id).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registra las tablas)
from app.models import Tenant, Transaction
from app.models.entities import Base
from app.services.holding_period import current_holding_starts


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _tx(db: Session, cid: int, day: date, action: str, qty: str, tenant_id=None) -> None:
    db.add(
        Transaction(
            company_id=cid,
            trade_date=day,
            action=action,
            quantity=Decimal(qty),
            price=Decimal("1"),
            tenant_id=tenant_id,
        )
    )


def test_empty_input_returns_empty(db):
    assert current_holding_starts(db, []) == {}


def test_simple_buy_marks_that_date(db):
    _tx(db, 1, date(2024, 1, 10), "buy", "3")
    db.commit()
    assert current_holding_starts(db, [1]) == {1: date(2024, 1, 10)}


def test_partial_sale_keeps_original_start(db):
    _tx(db, 1, date(2024, 1, 10), "buy", "3")
    _tx(db, 1, date(2024, 3, 1), "sell", "1")
    _tx(db, 1, date(2024, 4, 1), "buy", "1")
    db.commit()
    # Nunca se cerro la posicion: el inicio sigue siendo la primera compra.
    assert current_holding_starts(db, [1]) == {1: date(2024, 1, 10)}


def test_full_sale_and_rebuy_restarts_holding(db):
    _tx(db, 1, date(2024, 1, 10), "buy", "3")
    _tx(db, 1, date(2024, 3, 1), "sell", "3")
    _tx(db, 1, date(2024, 5, 20), "buy", "2")
    db.commit()
    assert current_holding_starts(db, [1]) == {1: date(2024, 5, 20)}


def test_full_sale_without_rebuy_keeps_last_opening_buy(db):
    # La funcion devuelve la compra que abrio la ULTIMA tenencia, este o no
    # abierta ahora: los llamadores (/positions, ficha de empresa) solo la
    # consultan para posiciones vivas, asi que el caso cerrado no se muestra.
    _tx(db, 1, date(2024, 1, 10), "buy", "3")
    _tx(db, 1, date(2024, 3, 1), "sell", "3")
    db.commit()
    assert current_holding_starts(db, [1]) == {1: date(2024, 1, 10)}


def test_sell_into_negative_then_buy_restarts(db):
    # Historial incompleto (la venta llega sin compra previa): la siguiente
    # compra abre una tenencia nueva.
    _tx(db, 1, date(2024, 2, 1), "sell", "2")
    _tx(db, 1, date(2024, 6, 1), "buy", "1")
    db.commit()
    assert current_holding_starts(db, [1]) == {1: date(2024, 6, 1)}


def test_non_buy_sell_actions_are_ignored(db):
    _tx(db, 1, date(2024, 1, 10), "dividend", "5")
    _tx(db, 1, date(2024, 2, 10), "BUY", "2")  # el case no importa
    db.commit()
    assert current_holding_starts(db, [1]) == {1: date(2024, 2, 10)}


def test_multiple_companies_in_one_query(db):
    for cid, day in ((1, date(2024, 1, 10)), (2, date(2024, 2, 15))):
        _tx(db, cid, day, "buy", "1")
    _tx(db, 2, date(2024, 3, 1), "sell", "1")
    _tx(db, 2, date(2024, 4, 1), "buy", "1")
    db.commit()
    assert current_holding_starts(db, [1, 2, 3]) == {
        1: date(2024, 1, 10),
        2: date(2024, 4, 1),
    }


def test_tenant_scope_is_respected(db):
    tenant_a = Tenant(external_id="hp-a", name="A")
    tenant_b = Tenant(external_id="hp-b", name="B")
    db.add_all([tenant_a, tenant_b])
    db.flush()
    _tx(db, 1, date(2024, 1, 10), "buy", "3", tenant_id=tenant_a.id)
    _tx(db, 1, date(2024, 3, 1), "sell", "3", tenant_id=tenant_a.id)
    _tx(db, 1, date(2024, 2, 1), "buy", "1", tenant_id=tenant_b.id)
    db.commit()
    db.info["tenant_id"] = tenant_a.id
    # El ledger de A va por su cuenta: su inicio es SU compra de enero, no la
    # de febrero de B. Sin el scope, la compra de B reabriria la tenencia de A.
    assert current_holding_starts(db, [1]) == {1: date(2024, 1, 10)}
    db.info["tenant_id"] = tenant_b.id
    assert current_holding_starts(db, [1]) == {1: date(2024, 2, 1)}
