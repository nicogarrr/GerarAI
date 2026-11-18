"""El «Desde» de la posicion respeta el orden de reproduccion del ledger.

Medido antes del fix: una venta editada a posteriori hasta una cantidad que
solo cabe gracias a una recompra del mismo dia se reproduce DESPUES de esa
compra (_replay_order, igual que rebuild_position: el coste medio sigue
continuo, 10@100 + 10@160 -> 5 a 130). Pero current_holding_starts recorria
el orden bruto de alta (venta primero): la tenencia pasaba por negativo y el
«Desde» saltaba al dia de la recompra. Misma posicion, dos verdades: coste
del lote de 2024 con antiguedad «nueva» y bucket corto_plazo.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position, Transaction
from app.services.holding_period import current_holding_starts
from app.services.portfolio_ledger_service import PortfolioLedgerService, _replay_order


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db):
    company = Company(
        ticker="PROBE",
        name="Probe",
        exchange="NASDAQ",
        currency="USD",
        sector="Tech",
        industry="Tech",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _ledger_with_deferred_same_day_sale(db, company):
    """Compra 10 (2024) + venta 10 y recompra 10 el mismo dia; la venta se
    edita despues a 15: solo cabe aplazada tras la recompra (_replay_order)."""
    service = PortfolioLedgerService()
    service.create_transaction(
        db,
        ticker=company.ticker,
        action="buy",
        quantity=Decimal("10"),
        price=Decimal("100"),
        trade_date=date(2024, 1, 1),
        fees=Decimal("0"),
        currency="EUR",
    )
    service.create_transaction(
        db,
        ticker=company.ticker,
        action="sell",
        quantity=Decimal("10"),
        price=Decimal("150"),
        trade_date=date(2026, 6, 1),
        fees=Decimal("0"),
        currency="EUR",
    )
    service.create_transaction(
        db,
        ticker=company.ticker,
        action="buy",
        quantity=Decimal("10"),
        price=Decimal("160"),
        trade_date=date(2026, 6, 1),
        fees=Decimal("0"),
        currency="EUR",
    )
    db.commit()
    sell = db.scalars(select(Transaction).where(Transaction.action == "sell")).one()
    sell.quantity = Decimal("15")
    db.flush()
    service.rebuild_position(db, company.id)
    db.commit()


def test_deferred_same_day_sale_keeps_the_original_holding_start(db):
    company = _company(db)
    _ledger_with_deferred_same_day_sale(db, company)
    position = db.scalars(select(Position).where(Position.company_id == company.id)).one()
    # El ledger no cerro la tenencia: 10@100 + 10@160 -> 5 a coste medio 130.
    assert position.quantity == Decimal("15") - Decimal("10")
    assert position.average_cost == Decimal("130")
    # El «Desde» tiene que contar la MISMA historia: lote abierto en 2024.
    assert current_holding_starts(db, [company.id]) == {company.id: date(2024, 1, 1)}


def test_mixed_case_action_is_replayed_consistently(db):
    """Repro del Auditor: la query de current_holding_starts filtra con
    func.lower (admite 'BUY'), asi que la reproduccion debe interpretar la
    accion con la MISMA normalizacion. Sin ella, _replay_order no reconocia
    la compra en mayusculas, aplazaba la venta de cierre al final y el
    «Desde» decia 2024 en una tenencia cerrada y reabierta en 2026.
    Las puertas de escritura normalizan a minuscula (Literal del modelo,
    create_transaction, importadores); la fila en mayusculas solo entra
    directa a BD, pero el filtro propio de la funcion la admite y la
    lectura tiene que ser coherente con ese filtro."""
    company = _company(db)
    for i, (day, action, qty) in enumerate(
        [
            (date(2024, 1, 1), "buy", 10),
            (date(2026, 6, 1), "BUY", 10),
            (date(2026, 6, 1), "sell", 20),
            (date(2026, 6, 1), "buy", 5),
        ]
    ):
        db.add(
            Transaction(
                company_id=company.id,
                trade_date=day,
                action=action,
                quantity=Decimal(qty),
                price=Decimal(1),
                created_at=datetime(2026, 6, 1) + timedelta(seconds=i),
            )
        )
    db.commit()
    # 10 + BUY 10 = 20; venta de 20 cierra la tenencia; la recompra de 5
    # abre una nueva el mismo dia.
    assert current_holding_starts(db, [company.id]) == {company.id: date(2026, 6, 1)}


def test_replay_order_treats_uppercase_buy_as_covering_purchase():
    """Test de ledger de la funcion compartida: _replay_order interpreta la
    accion con la misma normalizacion (case-insensitive) que el filtro de
    sus llamantes. Una venta que solo cabe gracias a un 'BUY' en mayusculas
    del mismo dia se aplaza tras el; con la comparacion exacta quedaba al
    final del dia y ningun consumidor veia el cierre real."""
    rows = [
        Transaction(
            trade_date=date(2026, 6, 1),
            action=action,
            quantity=Decimal(qty),
            price=Decimal(1),
            created_at=datetime(2026, 6, 1) + timedelta(seconds=i),
        )
        for i, (action, qty) in enumerate([("buy", 10), ("sell", 15), ("BUY", 10)])
    ]
    ordered = _replay_order(rows)
    # La venta de 15 se reproduce DESPUES del 'BUY' 10 que la cubre.
    assert [(row.action, row.quantity) for row in ordered] == [
        ("buy", Decimal(10)),
        ("BUY", Decimal(10)),
        ("sell", Decimal(15)),
    ]


def test_mixed_case_control_lowercase_same_result(db):
    """Control: el mismo ledger en minusculas da exactamente el mismo
    «Desde» (la normalizacion no cambia ningun ledger ya coherente)."""
    company = _company(db)
    for i, (day, action, qty) in enumerate(
        [
            (date(2024, 1, 1), "buy", 10),
            (date(2026, 6, 1), "buy", 10),
            (date(2026, 6, 1), "sell", 20),
            (date(2026, 6, 1), "buy", 5),
        ]
    ):
        db.add(
            Transaction(
                company_id=company.id,
                trade_date=day,
                action=action,
                quantity=Decimal(qty),
                price=Decimal(1),
                created_at=datetime(2026, 6, 1) + timedelta(seconds=i),
            )
        )
    db.commit()
    assert current_holding_starts(db, [company.id]) == {company.id: date(2026, 6, 1)}


def test_same_day_full_sale_and_rebuy_still_restarts_the_holding(db):
    """Venta que SI cabia al darse de alta: cierre + reapertura real el mismo
    dia; el «Desde» se reinicia (un mutante que nunca reinicie muere aqui)."""
    company = _company(db)
    service = PortfolioLedgerService()
    service.create_transaction(
        db,
        ticker=company.ticker,
        action="buy",
        quantity=Decimal("10"),
        price=Decimal("100"),
        trade_date=date(2024, 1, 1),
        fees=Decimal("0"),
        currency="EUR",
    )
    service.create_transaction(
        db,
        ticker=company.ticker,
        action="sell",
        quantity=Decimal("10"),
        price=Decimal("150"),
        trade_date=date(2026, 6, 1),
        fees=Decimal("0"),
        currency="EUR",
    )
    service.create_transaction(
        db,
        ticker=company.ticker,
        action="buy",
        quantity=Decimal("10"),
        price=Decimal("160"),
        trade_date=date(2026, 6, 1),
        fees=Decimal("0"),
        currency="EUR",
    )
    db.commit()
    assert current_holding_starts(db, [company.id]) == {company.id: date(2026, 6, 1)}
