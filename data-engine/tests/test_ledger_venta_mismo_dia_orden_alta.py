"""Compra y venta del mismo día: el orden de alta no convierte un ledger válido en «oversell».

``rebuild_position`` reproduce el ledger por (trade_date, created_at, id). Dentro
de un día eso es el orden en que se DIERON DE ALTA las filas, no el de
ejecución. Caso real: compra X el día 1, venta S el día 2, el usuario añade la
compra Y del día 2 (la buena) y borra X (fecha mal puesta). El ledger que queda
(compra 10 y venta 10 el mismo día) es válido, pero S se dio de alta antes que
Y: la reconstrucción vendía antes de comprar y lanzaba PortfolioOversellError,
así que el borrado (y cualquier reconstrucción: splits, ediciones) quedaba
bloqueado. Ahora una venta que no cabe se aplaza hasta las compras posteriores
del MISMO día; un ledger que ya era válido se reproduce exactamente igual.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Portfolio, Transaction
from app.services.portfolio_ledger_service import (
    PortfolioLedgerService,
    PortfolioOversellError,
)

D1 = date(2026, 3, 2)
D2 = date(2026, 3, 3)
D3 = date(2026, 3, 4)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-mismo-dia"
        session.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
        session.add(Company(
            ticker="REP", name="Repsol", exchange="BME", currency="EUR", sector="Energy",
            industry="Oil", company_type="operating", valuation_model="dcf",
            special_sources=[], special_risks=[], factor_tags=[], domicile_country="ES",
        ))
        session.commit()
        yield session


def _company(db) -> Company:
    return db.scalar(select(Company).where(Company.ticker == "REP"))


def _tx(db, trade_date, action, qty, price) -> Transaction:
    row = Transaction(
        company_id=_company(db).id, trade_date=trade_date, action=action,
        quantity=Decimal(qty), price=Decimal(price), fees=Decimal("0"), currency="EUR",
    )
    db.add(row)
    db.commit()
    return row


def test_venta_dada_de_alta_antes_que_su_compra_del_mismo_dia(db):
    svc = PortfolioLedgerService()
    x = _tx(db, D1, "buy", "10", "9")    # fecha equivocada, se borrará
    _tx(db, D2, "sell", "10", "12")      # alta antes que la compra buena
    _tx(db, D2, "buy", "15", "10")       # la compra real del mismo día
    db.delete(x)
    db.commit()
    position = svc.rebuild_position(db, _company(db).id, drop_when_empty=True)
    assert position is not None
    assert position.quantity == Decimal("5")
    assert position.realized_pnl == Decimal("20")        # (12 - 10) * 10
    assert position.cost_basis_native == Decimal("50")


def test_ledger_ya_valido_se_reproduce_igual(db):
    # Orden de alta compra->venta->compra el mismo día: nada se reordena (la
    # venta cabe con la compra del día anterior), coste y realizado como antes.
    svc = PortfolioLedgerService()
    _tx(db, D1, "buy", "10", "10")
    _tx(db, D2, "sell", "10", "12")
    _tx(db, D2, "buy", "5", "20")
    position = svc.rebuild_position(db, _company(db).id)
    assert position.quantity == Decimal("5")
    assert position.realized_pnl == Decimal("20")
    assert position.cost_basis_native == Decimal("100")


def test_venta_sin_compra_que_la_cubra_ese_dia_sigue_siendo_oversell(db):
    svc = PortfolioLedgerService()
    _tx(db, D2, "sell", "10", "12")
    _tx(db, D3, "buy", "10", "10")       # al día siguiente: no la cubre
    with pytest.raises(PortfolioOversellError):
        svc.rebuild_position(db, _company(db).id)


def test_compra_del_mismo_dia_no_cubre_mas_de_lo_que_compra(db):
    svc = PortfolioLedgerService()
    _tx(db, D2, "sell", "10", "12")
    _tx(db, D2, "buy", "4", "10")
    with pytest.raises(PortfolioOversellError):
        svc.rebuild_position(db, _company(db).id)


def test_varias_ventas_aplazadas_conservan_su_orden(db):
    svc = PortfolioLedgerService()
    _tx(db, D2, "sell", "3", "12")
    _tx(db, D2, "sell", "2", "15")
    _tx(db, D2, "buy", "6", "10")
    position = svc.rebuild_position(db, _company(db).id)
    assert position.quantity == Decimal("1")
    assert position.cost_basis_native == Decimal("10")
    assert position.realized_pnl == Decimal("16")  # 3*2 + 2*5
