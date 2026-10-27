"""calculate_all no repite la misma consulta de hechos por metrica.

Cada metrica calculada pedia sus hechos de entrada con ``_facts_for_metric``
(una consulta por empresa y metrica de entrada), y muchas metricas comparten
entradas (revenue, net_income, total_equity...). En /peers/comparison, que
llama a ``calculate_all`` para la empresa y sus 8 comparables, eran ~2.040
consultas de ``financial_facts`` para solo 250 distintas. Ahora, durante un
``calculate_all``, cada (empresa, metrica) se consulta una vez y se reutiliza.
Los resultados son exactamente los mismos.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact
from app.services.metric_calculation_service import MetricCalculationService

_METRICAS = {
    "revenue": "1000", "gross_profit": "450", "operating_income": "180", "net_income": "120",
    "ebitda": "250", "free_cash_flow": "100", "operating_cash_flow": "160", "capital_expenditure": "-60",
    "total_debt": "500", "cash_and_equivalents": "200", "total_equity": "800", "total_assets": "1900",
    "interest_expense": "20", "depreciation_amortization": "50", "income_tax_expense": "30",
    "current_assets": "600", "current_liabilities": "400", "shares_outstanding": "100",
    "shares_diluted": "102", "eps_diluted": "1.2", "market_cap": "3000",
}


def _sesion():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    company = Company(
        ticker="MET", name="Metricas", exchange="NYSE", currency="USD", sector="Tech",
        industry="Software", company_type="standard", valuation_model="standard_dcf",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    for year in range(2019, 2025):
        factor = Decimal(1) + Decimal(year - 2019) / 10
        for metric, value in _METRICAS.items():
            db.add(FinancialFact(
                company_id=company.id, metric=metric, value=Decimal(value) * factor,
                unit="shares" if metric.startswith("shares") else "USD",
                period=f"FY{year}", fiscal_year=year, source_type="sec_companyfacts", is_reported=True,
            ))
    db.commit()
    return engine, db, company


def _consultas_de_hechos(engine) -> tuple[list, Counter]:
    vistas: list = []
    def _on(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        if statement.lstrip().startswith("SELECT financial_facts"):
            vistas.append(tuple(params))
    event.listen(engine, "before_cursor_execute", _on)
    return vistas, Counter()


def _comparable(result):
    return (result.metric, result.status, result.period, result.value, result.numerator,
            result.denominator, tuple(result.source_fact_ids))


def test_calculate_all_consulta_cada_metrica_de_entrada_una_vez():
    engine, db, company = _sesion()
    vistas, _ = _consultas_de_hechos(engine)
    MetricCalculationService().calculate_all(db, company, persist=False)
    repetidas = {k: n for k, n in Counter(vistas).items() if n > 1}
    assert vistas, "calculate_all debe leer hechos"
    assert repetidas == {}, f"consultas repetidas: {len(vistas)} totales, {len(set(vistas))} distintas"


def test_calculate_all_da_los_mismos_resultados_que_metrica_a_metrica():
    engine, db, company = _sesion()
    service = MetricCalculationService()
    todas = [_comparable(r) for r in service.calculate_all(db, company, persist=False)]
    una_a_una = [
        _comparable(service.calculate(db, company, r[0], persist=False)) for r in todas
    ]
    assert todas == una_a_una
    assert any(r[1] == "ok" for r in todas)


def test_la_cache_no_sobrevive_a_calculate_all():
    engine, db, company = _sesion()
    service = MetricCalculationService()
    service.calculate_all(db, company, persist=False)
    # Un hecho nuevo despues de calculate_all se ve en la siguiente llamada.
    db.add(FinancialFact(
        company_id=company.id, metric="revenue", value=Decimal("5000"), unit="USD",
        period="FY2025", fiscal_year=2025, source_type="sec_companyfacts", is_reported=True,
    ))
    db.commit()
    hechos = service._facts_for_metric(db, company, "revenue")
    assert hechos[0].fiscal_year == 2025
