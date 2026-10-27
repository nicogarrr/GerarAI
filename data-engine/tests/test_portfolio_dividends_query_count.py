"""/portfolio/dividends: el numero de sentencias no crece con las posiciones.

``portfolio_yields`` lanzaba una consulta de ``DividendRecord`` POR CADA
posicion: con las 19 posiciones de la cartera de Nico eran 22 sentencias por
peticion (y 49 con 16 posiciones y mas historico en el escaner de N+1). Ahora
los dividendos TTM de todas las empresas en cartera salen de una sola consulta
y se agrupan por empresa en memoria. Este test fija que el coste no depende del
numero de posiciones y que el resultado (TTM, yield, cobertura) es el mismo.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, DividendRecord, Portfolio, Position
from app.services.dividend_ingestion_service import DividendIngestionService


def _seed(n_positions: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Portfolio(name="p", base_currency="EUR", is_default=True))
    db.flush()
    today = date.today()
    for i in range(n_positions):
        company = Company(
            ticker=f"DIV{i:03d}", name=f"DIV{i:03d}", exchange="NYSE", currency="USD",
            sector="Tech", industry="Tech", company_type="holding",
            valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
        )
        db.add(company)
        db.flush()
        db.add(Position(
            company_id=company.id, quantity=Decimal("10"), average_cost=Decimal("90"),
            market_price=Decimal("100"), market_value=Decimal("1000"),
            market_value_base=Decimal("900"), currency="USD", as_of=today,
        ))
        # Cuatro pagos dentro de la ventana TTM y uno fuera (hace mas de un año).
        for k, days in enumerate((30, 120, 210, 300, 400)):
            db.add(DividendRecord(
                company_id=company.id, ex_date=today - timedelta(days=days),
                amount=Decimal("0.5") + Decimal(i) / 100, currency="USD", source="fmp",
            ))
    db.commit()
    return engine, db


def _yields(n_positions: int):
    engine, db = _seed(n_positions)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    result = DividendIngestionService().portfolio_yields(db)
    db.close()
    return len(statements), result


def test_dividendos_de_cartera_no_escalan_con_las_posiciones():
    pocas, _ = _yields(3)
    muchas, resultado = _yields(30)
    assert muchas == pocas, (pocas, muchas)
    assert pocas <= 3
    assert len(resultado["positions"]) == 30


def test_dividendos_por_lotes_mantienen_ttm_y_yield():
    _, resultado = _yields(3)
    por_ticker = {p["ticker"]: p for p in resultado["positions"]}
    # DIV002: 4 pagos TTM de 0,52 = 2,08 por accion; yield = 2,08 / 100.
    p = por_ticker["DIV002"]
    assert p["records_12m"] == 4
    assert abs(p["ttm_dividend_per_share"] - 2.08) < 1e-9
    assert abs(p["dividend_yield"] - 0.0208) < 1e-12
    assert resultado["coverage"]["positions_with_dividend_data"] == 3
    # Agregado ponderado por valor base (900 cada una): media de 2,00/2,04/2,08 %.
    assert abs(resultado["portfolio_yield"] - (0.0200 + 0.0204 + 0.0208) / 3) < 1e-12
