"""ScreenerService.run: la lectura de calculated_metrics se acota a la ultima
fila por (empresa, metrica).

Antes leia TODA la tabla calculated_metrics que pasara el filtro (todos los
años y periodos) para usar solo la primera fila por (empresa, metrica) en el
orden (fiscal_year DESC NULLS LAST, id DESC). Ahora un row_number() con ese
mismo orden y rn = 1 devuelve exactamente esas filas. Observaciones y
resultados son identicos.

Run from data-engine/:
    pytest tests/test_screener_calculated_bound.py -v
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base, CalculatedMetric, Company
from app.services.screener_service import ScreenerService


@pytest.fixture
def env():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
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
    db.flush()
    # 20 años de historia: solo el mas reciente debe llegar a observaciones.
    for year in range(2006, 2026):
        db.add(
            CalculatedMetric(
                company_id=company.id,
                metric="pe_ratio",
                value=Decimal(str(year)),
                unit="x",
                period="annual",
                fiscal_year=year,
                status="ok",
                definition_version="v1",
                formula="x",
                source_fact_ids=[],
                calculation_trace={},
                confidence=Decimal("0.7"),
            )
        )
    db.commit()
    statements: list[str] = []
    event.listen(
        engine, "before_cursor_execute", lambda conn, cur, stmt, params, ctx, many: statements.append(stmt)
    )
    return db, company, statements


def test_lectura_calculada_acotada(env):
    db, _, statements = env
    ScreenerService().run(db, criteria=[{"left": "pe_ratio", "operator": "<", "right": "3000"}])
    reads = [
        s
        for s in statements
        if s.lstrip().upper().startswith("SELECT") and "FROM CALCULATED_METRICS" in s.upper()
    ]
    assert reads, "se esperaba la lectura de calculated_metrics"
    for stmt in reads:
        low = stmt.lower()
        assert "row_number()" in low and "over" in low, stmt


def test_observaciones_identicas_ultimo_anyo(env):
    db, company, _ = env
    result = ScreenerService().run(db, criteria=[{"left": "pe_ratio", "operator": "<", "right": "3000"}])
    (row,) = [r for r in result["results"] if r["company_id"] == company.id]
    # Ultimo fiscal_year (2025), no la media ni otro año.
    assert row["criteria"][0]["left_value"] == "2025.00000000"
    assert row["matched"] is True


def test_lectura_calculada_acotada_a_metricas_referenciadas(env):
    """La ventana solo rankea las metricas que la corrida referencia.

    Una metrica calculada que el criterio no usa no entra en el IN de la
    subconsulta (antes se rankeaban TODAS las del tenant) y no aparece en
    ninguna parte del resultado por empresa.
    """
    db, company, statements = env
    db.add(
        CalculatedMetric(
            company_id=company.id,
            metric="metrica_no_usada",
            value=Decimal("999"),
            unit="x",
            period="annual",
            fiscal_year=2025,
            status="ok",
            definition_version="v1",
            formula="x",
            source_fact_ids=[],
            calculation_trace={},
            confidence=Decimal("0.7"),
        )
    )
    db.commit()
    result = ScreenerService().run(db, criteria=[{"left": "pe_ratio", "operator": "<", "right": "3000"}])
    window_reads = [
        s
        for s in statements
        if "row_number()" in s.lower() and "from calculated_metrics" in s.lower()
    ]
    assert window_reads, "se esperaba la lectura con ventana de calculated_metrics"
    for stmt in window_reads:
        assert "calculated_metrics.metric IN" in stmt, stmt
        assert "metrica_no_usada" not in stmt or "pe_ratio" in stmt
    (row,) = [r for r in result["results"] if r["company_id"] == company.id]
    assert row["matched"] is True
    assert "metrica_no_usada" not in str(row)
