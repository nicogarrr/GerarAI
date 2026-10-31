"""La terminal financiera leia TODOS los facts y metricas calculadas de la
empresa para luego descartar en Python los años fuera de la ventana.

Ahora la ventana se acota en SQL (los años NULL pasan, como antes) y el
ultimo año se calcula con MAX agregado barato antes de la lectura grande.
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base
from app.services.financial_terminal_service import FinancialTerminalService
from tests.test_financial_terminal_service import _calculated, _company, _fact


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def test_terminal_bounds_series_window_in_sql(db):
    company = _company(db)
    for year in range(2010, 2026):
        _fact(db, company, period=f"{year}-12-31:FY", fiscal_year=year, value=year)
    statements = []
    engine = db.get_bind()

    def _capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM financial_facts" in statement or "FROM calculated_metrics" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        FinancialTerminalService().build(db, company, metrics=["revenue"], years=10)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
    reads = [s for s in statements if "fiscal_year >=" in s or "fiscal_year IS NULL" in s]
    # La lectura grande de cada tabla lleva la cota de ventana (los MAX
    # agregados no la necesitan: son baratos y no leen filas).
    assert reads, "la lectura de series sigue sin acotar la ventana en SQL"


def test_terminal_window_keeps_null_years_and_drops_old(db):
    company = _company(db)
    _fact(db, company, period="2010-12-31:FY", fiscal_year=2010, value=1)
    _fact(db, company, period="2024-12-31:FY", fiscal_year=2024, value=2)
    _fact(db, company, period="desconocido", fiscal_year=None, value=3)
    _calculated(db, company, period="2011-12-31:FY", fiscal_year=2011, value=0.1)
    _calculated(db, company, period="2025-12-31:FY", fiscal_year=2025, value=0.2)
    out = FinancialTerminalService().build(db, company, metrics=["revenue", "roic"], years=10)
    metrics = {m["metric"]: m for m in out["metrics"]}
    revenue_years = {row["fiscal_year"] for row in metrics["revenue"]["series"]}
    roic_years = {row["fiscal_year"] for row in metrics["roic"]["series"]}
    assert revenue_years == {2024, None}
    assert roic_years == {2025}
