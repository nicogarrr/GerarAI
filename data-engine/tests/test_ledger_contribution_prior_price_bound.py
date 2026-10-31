"""_ledger_contribution: el cierre previo al cutoff se acota en SQL.

Antes leia TODA la historia de precios anterior al cutoff (filas ORM
completas, ordenadas) para quedarse con la ultima por empresa. Ahora un
row_number() OVER (PARTITION BY company ORDER BY date DESC, id DESC) = 1
acota la lectura a exactamente una fila por empresa, determinista, y solo
se proyectan las columnas usadas (company_id, date, adj_close). La fila
elegida es la ultima estrictamente anterior al cutoff.

Run from data-engine/:
    pytest tests/test_ledger_contribution_prior_price_bound.py -v
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    CashBalance,
    Company,
    MarketPrice,
    Portfolio,
    Position,
    Transaction,
)
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService

CUTOFF = date(2026, 1, 1)


@pytest.fixture
def env():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(CashBalance(currency="USD", balance=Decimal("0")))
    company = Company(
        ticker="AAA",
        name="AAA",
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
    portfolio = Portfolio(name="p", base_currency="USD")
    db.add(portfolio)
    db.flush()
    position = Position(
        portfolio_id=portfolio.id,
        company_id=company.id,
        quantity=Decimal("10"),
        average_cost=Decimal("100"),
        market_price=Decimal("150"),
        market_value=Decimal("1500"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        as_of=date.today(),
        currency="USD",
        base_currency="USD",
        market_value_base=Decimal("1500"),
    )
    db.add(position)
    db.add(
        Transaction(
            company_id=company.id,
            trade_date=date(2025, 6, 1),
            action="buy",
            quantity=Decimal("10"),
            price=Decimal("100"),
            fees=Decimal("0"),
            currency="USD",
            raw_payload={},
        )
    )
    # Historia larga anterior al cutoff: lo que NO debe leerse entero.
    for i in range(1, 201):
        day = CUTOFF - timedelta(days=i)
        db.add(
            MarketPrice(
                company_id=company.id,
                date=day,
                open=Decimal("100"),
                high=Decimal("100"),
                low=Decimal("100"),
                close=Decimal("120" if i == 1 else "90"),
                adj_close=Decimal("120" if i == 1 else "90"),
                volume=1,
                source="test",
            )
        )
    db.commit()
    statements: list[str] = []
    event.listen(
        engine, "before_cursor_execute", lambda conn, cur, stmt, params, ctx, many: statements.append(stmt)
    )
    return db, company, position, statements


def test_lectura_previa_al_cutoff_acotada(env):
    db, company, position, statements = env
    PortfolioIntelligenceService()._ledger_contribution(db, [(position, company)], CUTOFF)
    prior = [
        s
        for s in statements
        if s.lstrip().upper().startswith("SELECT")
        and "FROM MARKET_PRICES" in s.upper()
        and "market_prices.date <" in s
    ]
    assert prior, "se esperaba la lectura de cierres previos al cutoff"
    for stmt in prior:
        # Acotada: row_number() por empresa (rn = 1), no barrido completo.
        assert "row_number()" in stmt.lower() and "over" in stmt.lower(), stmt


def test_mismo_cierre_elegido_y_mismo_resultado(env):
    db, company, position, _ = env
    result = PortfolioIntelligenceService()._ledger_contribution(db, [(position, company)], CUTOFF)
    (row,) = result["positions"]
    # Ultima pre-cutoff: adj_close 120 (la de 2025-12-31), no las de 90.
    assert row["start_value"] == 1200.0
    assert row["contribution_pnl"] == 300.0


def test_seleccion_determinista_una_fila_por_empresa(env):
    """La lectura previa al cutoff elige exactamente 1 fila por empresa con
    row_number(date DESC, id DESC): determinista incluso si una base de datos
    con drift de esquema tuviera duplicados de fecha (el modelo los prohibe
    con uq_market_price_company_date desde 0001). La version MAX(date)+join
    traia TODAS las filas empatadas y el dict elegia por orden indefinido.
    """
    db, company, position, statements = env
    PortfolioIntelligenceService()._ledger_contribution(db, [(position, company)], CUTOFF)
    prior = [
        s
        for s in statements
        if s.lstrip().upper().startswith("SELECT")
        and "FROM MARKET_PRICES" in s.upper()
        and "market_prices.date <" in s
    ]
    assert prior, "se esperaba la lectura de cierres previos al cutoff"
    for stmt in prior:
        low = stmt.lower()
        assert "row_number()" in low and "over" in low, stmt
        # Desempate determinista: fecha desc y, a igual fecha, id desc.
        assert "date desc" in low and "id desc" in low, stmt
