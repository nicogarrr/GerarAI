"""Debug test to see actual queries."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base, CashBalance, Company, Portfolio, Position
from app.services.risk_service import RiskService


def test_debug_queries():
    """Print all queries to see what's happening."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    
    # Create minimal portfolio
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    db.flush()
    
    today = date.today()
    for i in range(3):
        company = Company(
            ticker=f"TEST{i}",
            name=f"Test {i}",
            exchange="NASDAQ",
            currency="USD",
            sector="Tech",
            industry="Software",
            company_type="growth",
            valuation_model="dcf",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.flush()
        
        db.add(Position(
            company_id=company.id,
            quantity=Decimal("10"),
            market_price=Decimal("100"),
            market_value=Decimal("1000"),
            market_value_base=Decimal("900"),
            currency="USD",
            base_currency="EUR",
            fx_rate=Decimal("0.9"),
            as_of=today,
        ))
    
    db.add(CashBalance(
        currency="EUR",
        balance=Decimal("1000"),
        settled_cash=Decimal("1000"),
        as_of=today,
    ))
    db.commit()
    
    # Clear and start tracking
    statements: list[str] = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    
    event.listen(engine, "before_cursor_execute", capture)
    
    service = RiskService()
    result = service.dashboard(db)
    
    selects = [s for s in statements if s.strip().upper().startswith("SELECT")]
    
    print(f"\n=== Total SELECT queries: {len(selects)} ===\n")
    for i, query in enumerate(selects, 1):
        print(f"--- Query {i} ---")
        print(query)
        print()
    
    assert result is not None
