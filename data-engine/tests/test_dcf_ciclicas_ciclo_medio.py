"""Cíclicas en el DCF estándar: margen FCF de ciclo medio (media de 5 ejercicios).

Decisión de Nico (4-nov-2026, 11:40): «mete todo lo que mejores resultados
tenga». El backtest point-in-time 2 (82 empresas, 2015–2026) bajó el error
mediano a 12 meses de petróleo, minería, acero y coches del 99 % al 53 % en
2021–26 con la media de 5 ejercicios del margen FCF real, crecimiento plano
igual al terminal y sin normalización de capex. Los semiconductores quedan
fuera (empeoran el backtest). La regla va por industria, nunca por ticker.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import CalculatedMetric, Company, FinancialFact, MarketPrice
from app.models.entities import Base
from app.valuation.cyclical_midcycle import (
    CYCLICAL_MIDCYCLE_MIN_YEARS,
    CYCLICAL_MIDCYCLE_YEARS,
    cyclical_industry_groups,
)
from app.valuation.dcf_fcff import DCFInputs, run_dcf
from app.valuation.engines.standard_dcf import StandardDCFEngine

M = 1_000_000
SHARES = 1_000 * M
NET_DEBT = 5_000 * M
WACC = 0.09

# Petrolera sintética: el último ejercicio (FY2025) está en el valle del ciclo
# (margen FCF 4 %), con capex de crecimiento sobre la amortización (dispararía
# la normalización de capex) y un rebote de ingresos del 12 % (dispararía el
# DCF multietapa). Millones de US$.
OIL = {
    2019: dict(
        revenue=40_000, operating_cash_flow=9_000, capital_expenditure=-6_000, depreciation_amortization=5_000
    ),
    2020: dict(
        revenue=30_000, operating_cash_flow=4_000, capital_expenditure=-4_500, depreciation_amortization=5_000
    ),
    2021: dict(
        revenue=45_000,
        operating_cash_flow=15_000,
        capital_expenditure=-5_000,
        depreciation_amortization=5_000,
    ),
    2022: dict(
        revenue=78_000,
        operating_cash_flow=28_000,
        capital_expenditure=-8_000,
        depreciation_amortization=6_000,
    ),
    2023: dict(
        revenue=56_000,
        operating_cash_flow=19_000,
        capital_expenditure=-10_000,
        depreciation_amortization=6_500,
    ),
    2024: dict(
        revenue=50_000,
        operating_cash_flow=15_000,
        capital_expenditure=-11_000,
        depreciation_amortization=7_000,
    ),
    2025: dict(
        revenue=56_000,
        operating_cash_flow=12_240,
        capital_expenditure=-10_000,
        depreciation_amortization=7_000,
    ),
}


def _margin(row):
    return (row["operating_cash_flow"] - abs(row["capital_expenditure"])) / row["revenue"]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _fact(db, company, metric, value, year, unit="USD"):
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal(str(value)),
            unit=unit,
            period=f"{year}-12-31:FY",
            fiscal_year=year,
            fiscal_quarter="FY",
            source_type="SEC",
            is_reported=True,
            confidence=Decimal("0.90"),
        )
    )


def _seed(db, ticker, raw, *, industry, sector="Energy", price=50.0, valuation_model="unassigned"):
    company = Company(
        ticker=ticker,
        name=f"{ticker} test",
        exchange="TEST",
        currency="USD",
        sector=sector,
        industry=industry,
        company_type="research_candidate",
        valuation_model=valuation_model,
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    years = sorted(raw)
    for i, year in enumerate(years):
        row = raw[year]
        for metric, value in row.items():
            _fact(db, company, metric, value * M, year)
        fcf = row["operating_cash_flow"] - abs(row["capital_expenditure"])
        _fact(db, company, "free_cash_flow", fcf * M, year)
        _fact(db, company, "fcf_margin", round(fcf / row["revenue"], 6), year, unit="decimal")
        if i:
            growth = row["revenue"] / raw[years[i - 1]]["revenue"] - 1
            _fact(db, company, "revenue_growth", round(growth, 6), year, unit="decimal")
        _fact(db, company, "shares_diluted", SHARES, year, unit="shares")
        _fact(db, company, "net_debt", NET_DEBT, year)
    db.add(
        CalculatedMetric(
            company_id=company.id,
            metric="wacc",
            value=Decimal(str(WACC)),
            unit="decimal",
            period=f"{years[-1]}-12-31:FY",
            fiscal_year=years[-1],
            status="ok",
            definition_version="WACC_STANDARD_V1",
            formula="ke*E/(D+E) + kd*(1-t)*D/(D+E)",
        )
    )
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date(2026, 11, 3),
            close=Decimal(str(price)),
            adj_close=Decimal(str(price)),
            source="test",
        )
    )
    db.commit()
    return company


def _seed_partial(db, ticker, raw):
    company = Company(
        ticker=ticker,
        name=f"{ticker} test",
        exchange="TEST",
        currency="USD",
        sector="Energy",
        industry="Oil & Gas E&P",
        company_type="research_candidate",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    for year, row in raw.items():
        for metric, value in row.items():
            _fact(db, company, metric, value * M, year)
    db.commit()
    return company


def _value(db, company, price=50.0):
    engine = StandardDCFEngine()
    return engine.value(engine.build_context(db, company, price))


def test_constants_are_the_backtest_winner():
    assert CYCLICAL_MIDCYCLE_YEARS == 5
    assert CYCLICAL_MIDCYCLE_MIN_YEARS == 3


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (("Energy", "Oil, Gas & Fuels"), ["oil_gas"]),
        (("Oil & Gas E&P", None), ["oil_gas"]),
        (("Oil & Gas Integrated", None), ["oil_gas"]),
        (("Energy", "Oilfield Services & Equipment"), ["oil_gas"]),
        (("Metals & Mining", "Mining & Metals"), ["mining_metals"]),
        (("Steel", None), ["mining_metals"]),
        (("Copper", None), ["mining_metals"]),
        (("Automobiles", "Automobiles"), ["autos"]),
        (("Auto Manufacturers", None), ["autos"]),
        # No cíclicas por esta regla:
        (("Semiconductors", "Semiconductors & Chip Equipment"), []),
        (("Auto Components", "Auto Parts"), []),
        (("Oil & Gas Midstream", None), []),
        (("Utilities", "Gas Utilities"), []),
        (("Technology", "Software"), []),
        (("Energy", None), []),
        ((None, None), []),
    ],
)
def test_cyclical_industry_groups_by_industry_text(labels, expected):
    assert cyclical_industry_groups(*labels) == expected


def test_oil_company_uses_five_year_midcycle_margin_flat_growth_no_capex_norm(db):
    company = _seed(db, "OILX", OIL, industry="Oil & Gas E&P")
    result = _value(db, company)

    midcycle = sum(_margin(OIL[y]) for y in range(2021, 2026)) / 5
    assert result["status"] == "ok"
    trace = result["trace"]
    flag = trace["cyclical_midcycle"]
    assert flag["applied"] is True
    assert flag["industries_matched"] == ["oil_gas"]
    assert flag["years_used"] == 5
    assert [p["fiscal_year"] for p in flag["periods"]] == [2025, 2024, 2023, 2022, 2021]
    assert flag["margin"] == pytest.approx(midcycle)
    # Sin normalización de capex ni etapa de crecimiento alto: DCF plano de 5
    # años con el margen de ciclo medio y crecimiento = terminal.
    assert "projection" not in trace or not trace.get("projection")
    assert trace["growth_source"] == "cyclical_flat_terminal"
    expected_base = run_dcf(
        DCFInputs(
            revenue=OIL[2025]["revenue"] * M,
            revenue_growth=0.03,
            fcf_margin=midcycle,
            wacc=WACC,
            terminal_growth=0.03,
            net_debt=NET_DEBT,
            shares_outstanding=SHARES,
        )
    ).value_per_share
    assert result["base_value"] == pytest.approx(expected_base)


def test_cyclical_with_fewer_than_three_years_keeps_todays_method(db):
    short = {year: OIL[year] for year in (2024, 2025)}
    company = _seed(db, "OILS", short, industry="Oil & Gas E&P")
    result = _value(db, company)
    flag = result["trace"]["cyclical_midcycle"]
    assert flag["applied"] is False
    assert flag["years_used"] == 2
    assert "mínimo 3" in flag["reason"]
    assert result["trace"]["growth_source"] != "cyclical_flat_terminal"


def test_midcycle_window_ignores_stale_cash_flow_years(db):
    # Flujo operativo y capex solo hasta FY2022, ingresos hasta FY2025: en la
    # ventana FY2021–FY2025 solo hay 2 ejercicios completos, así que no se
    # promedia un ciclo de hace años; sigue el método habitual con el motivo.
    stale = {}
    for year, row in OIL.items():
        stale[year] = dict(row) if year <= 2022 else {"revenue": row["revenue"]}
    company = _seed_partial(db, "OILG", stale)
    from app.valuation.cyclical_midcycle import midcycle_fcf_margin

    result = midcycle_fcf_margin(db, company.id, None)
    assert result["applied"] is False
    assert [p["fiscal_year"] for p in result["periods"]] == [2022, 2021]
    assert "últimos 5" in result["reason"]


def test_cyclical_with_non_positive_midcycle_margin_is_not_valued(db):
    burn = {
        year: dict(row, operating_cash_flow=abs(row["capital_expenditure"]) * 0.8)
        for year, row in OIL.items()
    }
    company = _seed(db, "OILB", burn, industry="Metals & Mining", sector="Materials")
    result = _value(db, company)
    assert result["status"] != "ok"
    assert result["expected_value"] is None
    assert "positive_midcycle_fcf_margin" in result["missing_inputs"]
    assert "ciclo medio" in result["trace"]["reason"]
    assert result["trace"]["cyclical_midcycle"]["margin"] < 0


def test_declared_valuation_model_prevails_over_industry_rule(db):
    company = _seed(
        db,
        "AUTX",
        OIL,
        industry="Automobiles",
        sector="Consumer Discretionary",
        valuation_model="scenario_auto_energy_fsd",
    )
    result = _value(db, company)
    flag = result["trace"]["cyclical_midcycle"]
    assert flag["applied"] is False
    assert flag["industries_matched"] == ["autos"]
    assert "método declarado" in flag["reason"]
    assert result["trace"]["growth_source"] != "cyclical_flat_terminal"


def test_semiconductor_is_not_treated_as_cyclical(db):
    company = _seed(db, "SEMX", OIL, industry="Semiconductors", sector="Technology")
    result = _value(db, company)
    assert result["status"] == "ok"
    assert result["trace"].get("cyclical_midcycle") is None
    assert result["trace"]["growth_source"] == "financial_facts"


def test_non_cyclical_company_unchanged(db):
    company = _seed(db, "SOFT", OIL, industry="Software", sector="Technology")
    result = _value(db, company)
    assert result["trace"].get("cyclical_midcycle") is None
