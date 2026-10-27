"""Ratios con denominador negativo -> N/D (auditoría de fórmulas,
``ratios_negative_denominator``).

Damodaran, "Return Measures": un ROE con patrimonio negativo no tiene
sentido; lo mismo ROA/ROIC con activo o capital invertido negativos, deuda
neta/EBITDA con EBITDA negativo, la conversión FCF con pérdidas o un margen
sobre ingresos negativos. Antes solo se descartaba el denominador == 0.
"""

from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.services.metric_calculation_service import MetricCalculationService
from tests.test_calculated_metrics import (
    add_fact,
    cleanup_metric_test_artifacts,
    create_test_company,
)

P = "2025-12-31:FY"


@pytest.mark.parametrize(
    ("metric", "facts", "engañoso"),
    [
        # NI −50 / patrimonio −200 = +0,25: aparenta un 25 % con pérdidas.
        ("roe", {"net_income": "-50", "total_equity": "-200"}, Decimal("0.25")),
        # EBITDA −10, deuda neta 100 -> −10x, que parece "mejor" que 2x.
        ("net_debt_to_ebitda", {"net_debt": "100", "ebitda": "-10"}, Decimal("-10")),
        # FCF 30 / beneficio −60 = −0,5: conversión sin sentido con pérdidas.
        ("fcf_conversion", {"free_cash_flow": "30", "net_income": "-60"}, Decimal("-0.5")),
    ],
)
def test_denominador_negativo_es_no_disponible(metric, facts, engañoso):
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        for name, value in facts.items():
            add_fact(db, company, name, value, period=P, fiscal_year=2025)
        db.commit()
        result = MetricCalculationService().calculate(db, company, metric, persist=False)
        assert result.value != engañoso
        assert result.status == "unavailable"
        assert result.value is None
        assert result.calculation_trace["reason"] == "non_positive_denominator"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_denominador_positivo_sigue_calculando():
    """Control a mano: NI −50 / patrimonio 200 = −0,25 (pérdida real)."""
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "net_income", "-50", period=P, fiscal_year=2025)
        add_fact(db, company, "total_equity", "200", period=P, fiscal_year=2025)
        db.commit()
        result = MetricCalculationService().calculate(db, company, "roe", persist=False)
        assert result.status == "ok"
        assert result.value == Decimal("-0.25000000")
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_ventana_5y_excluye_anios_con_patrimonio_negativo():
    """ROE medio: 2021 NI −50 / patrimonio −100 = +0,5 (engañoso) queda fuera.
    2022-2024: 10/100, 20/100, 30/100 -> media (0,1 + 0,2 + 0,3) / 3 = 0,2.
    Antes entraba el año engañoso: (0,5 + 0,6) / 4 = 0,275."""
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        rows = {2021: ("-50", "-100"), 2022: ("10", "100"), 2023: ("20", "100"), 2024: ("30", "100")}
        for year, (ni, equity) in rows.items():
            add_fact(db, company, "net_income", ni, period=f"{year}-12-31:FY", fiscal_year=year)
            add_fact(db, company, "total_equity", equity, period=f"{year}-12-31:FY", fiscal_year=year)
        db.commit()
        result = MetricCalculationService().calculate(db, company, "roe_5y", persist=False)
        assert result.status == "ok"
        assert result.value == Decimal("0.20000000")
        assert result.period == "FY2022-FY2024"
    finally:
        db.close()
        cleanup_metric_test_artifacts()
