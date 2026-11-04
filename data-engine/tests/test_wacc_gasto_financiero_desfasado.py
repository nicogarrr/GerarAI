"""El coste de la deuda no mezcla el gasto financiero de un ejercicio viejo con la deuda actual.

CHTR (prod, WACC «ok» del 25-sep-2026): coste de la deuda = gasto financiero
FY2013 (846 M$) / deuda FY2025 (94.756 M$) = 0,89 %. El gasto financiero
reciente no estaba ingerido con ese concepto y ``_match_alias(...,
allow_latest=True)`` cogió el último disponible, de hace 12 años. Con
deuda al 86 % el WACC salía 1,72 %, por debajo del crecimiento terminal
(3 %), y la tesis de CHTR caía entera (runs 133 y 166).

Regla general que fija este test (cualquier empresa): un flujo (gasto
financiero) solo se divide por un saldo (deuda) del mismo ejercicio o con
como mucho dos ejercicios de desfase (hueco de ingesta habitual). Si el
único dato es más viejo, el coste de la deuda se declara ausente (gate auditable en la traza) y el WACC queda ``unavailable``, como
cualquier otro input no creíble; no se inventa un coste por defecto.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact
from app.services.metric_calculation_service import MetricCalculationService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "CABLEX") -> Company:
    company = Company(
        ticker=ticker,
        name="Cablera sintética",
        exchange="TEST",
        currency="USD",
        sector="Communication Services",
        industry="Telecom Services",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fact(company, metric, value, *, year=2025, source_type="wacc_test", unit="USD"):
    return FinancialFact(
        company_id=company.id,
        metric=metric,
        value=Decimal(value),
        unit=unit,
        period=f"{year}-12-31:FY",
        fiscal_year=year,
        fiscal_quarter="FY",
        source_type=source_type,
        is_reported=True,
        confidence=Decimal("0.90"),
    )


def _inputs(db: Session, company: Company, *, interest_year: int) -> None:
    rows = [
        _fact(company, "risk_free_rate", "0.0511"),
        _fact(company, "beta", "0.687"),
        _fact(company, "equity_risk_premium", "0.0433"),
        _fact(company, "country_risk_premium", "0"),
        _fact(company, "effective_tax_rate", "0.227"),
        _fact(company, "total_debt", "94756000000", source_type="SEC"),
        _fact(company, "market_cap", "15276516352", source_type="yfinance"),
        _fact(company, "interest_expense", "846000000", year=interest_year, source_type="SEC"),
    ]
    db.add_all(rows)
    db.commit()


def _wacc(db, company):
    return MetricCalculationService().calculate(db, company, "wacc", persist=False)


@pytest.mark.parametrize("interest_year", [2013, 2022], ids=["doce_anos_chtr", "tres_anos"])
def test_gasto_financiero_viejo_no_entra_en_el_coste_de_la_deuda(db, interest_year):
    company = _company(db)
    _inputs(db, company, interest_year=interest_year)

    result = _wacc(db, company)
    trace = result.calculation_trace

    # Antes: status ok con WACC ~1,7 % (coste de deuda 0,89 %).
    assert result.status == "unavailable"
    assert result.value is None
    assert "interest_expense_same_period_as_debt" in trace["missing_inputs"]
    gated = [g for g in trace.get("gated_inputs") or [] if g["input"] == "interest_expense"]
    assert len(gated) == 1
    assert gated[0]["reason"] == "interest_expense_stale_vs_debt"
    assert gated[0]["resolution"] == "treated_as_absent"
    assert str(interest_year) in gated[0]["detail"] and "2025" in gated[0]["detail"]


@pytest.mark.parametrize(
    "interest_year", [2025, 2024, 2023], ids=["mismo_ejercicio", "contiguo", "dos_anos"]
)
def test_gasto_financiero_del_mismo_ejercicio_o_cercano_sigue_valiendo(db, interest_year):
    company = _company(db, ticker=f"CAB{interest_year}")
    _inputs(db, company, interest_year=interest_year)

    result = _wacc(db, company)

    assert result.status == "ok"
    assert result.calculation_trace["cost_of_debt_source"] == "interest_expense_over_debt"
    assert Decimal(result.calculation_trace["cost_of_debt"]) == pytest.approx(
        Decimal("846000000") / Decimal("94756000000")
    )
