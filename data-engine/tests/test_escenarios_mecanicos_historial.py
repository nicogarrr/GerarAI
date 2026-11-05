"""Escenarios mecánicos del DCF estándar: amplitud acotada por el historial propio.

Owner (Nico, 4-nov-2026): «escenarios reales, no hardcodeo». El optimista y el
pesimista mecánicos movían SIEMPRE ±8 pp de crecimiento y ±6 pp de margen FCF.
Sobre una empresa de margen bajo y estable eso no es un escenario: UNH (margen
FCF 3,6 %, rango propio 3,6–7,8 % en 7 ejercicios) salía con un optimista de
2.708 $ frente a un base de 469 $ y el esperado se iba a 755 $ (consenso 477 $).
Ahora la amplitud es la mitad del rango que ha recorrido la propia empresa en
sus últimos ejercicios (hechos FY), con ±8/±6 pp como techo. El caso base no
cambia (es lo que valida el backtest point-in-time).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import CalculatedMetric, Company, FinancialFact, MarketPrice
from app.models.entities import Base
from app.valuation.engines.standard_dcf import StandardDCFEngine
from app.valuation.scenario_definitions import (
    MECHANICAL_GROWTH_SHIFT,
    MECHANICAL_MARGIN_SHIFT,
    OWN_HISTORY_MIN_POINTS,
    OWN_HISTORY_YEARS,
    mechanical_dcf_scenarios,
    own_history_ranges,
)

M = 1_000_000

# Aseguradora sintética: ingresos que crecen 6–14 % y margen FCF 4–7 %.
STABLE = {
    2019: dict(revenue=1000, operating_cash_flow=80, capital_expenditure=-10),
    2020: dict(revenue=1060, operating_cash_flow=84, capital_expenditure=-10),
    2021: dict(revenue=1180, operating_cash_flow=93, capital_expenditure=-11),
    2022: dict(revenue=1340, operating_cash_flow=106, capital_expenditure=-12),
    2023: dict(revenue=1500, operating_cash_flow=118, capital_expenditure=-13),
    2024: dict(revenue=1620, operating_cash_flow=100, capital_expenditure=-14),
    2025: dict(revenue=1800, operating_cash_flow=86, capital_expenditure=-14),
}


def _rows(raw):
    return {y: {k: float(v) for k, v in r.items()} for y, r in raw.items()}


def test_constantes():
    assert (MECHANICAL_GROWTH_SHIFT, MECHANICAL_MARGIN_SHIFT) == (0.08, 0.06)
    assert (OWN_HISTORY_YEARS, OWN_HISTORY_MIN_POINTS) == (7, 4)


def test_rangos_del_historial_a_mano():
    h = own_history_ranges(_rows(STABLE))
    margins = [(r["operating_cash_flow"] + r["capital_expenditure"]) / r["revenue"] for r in STABLE.values()]
    assert h["fcf_margin"]["half_range"] == pytest.approx((max(margins) - min(margins)) / 2)
    assert h["fcf_margin"]["years"] == [2025, 2024, 2023, 2022, 2021, 2020, 2019]
    growths = [STABLE[y]["revenue"] / STABLE[y - 1]["revenue"] - 1 for y in range(2020, 2026)]
    assert h["revenue_growth"]["half_range"] == pytest.approx((max(growths) - min(growths)) / 2)
    assert h["revenue_growth"]["years"] == [2025, 2024, 2023, 2022, 2021, 2020]


def test_con_pocos_ejercicios_no_hay_rango():
    raw = {y: STABLE[y] for y in (2023, 2024, 2025)}
    h = own_history_ranges(_rows(raw))
    assert h == {"fcf_margin": None, "revenue_growth": None}


def test_historial_estrecho_acota_la_amplitud():
    h = own_history_ranges(_rows(STABLE))
    gs, ms = h["revenue_growth"]["half_range"], h["fcf_margin"]["half_range"]
    assert gs < 0.08 and ms < 0.06
    bear, base, bull = mechanical_dcf_scenarios(0.10, 0.05, 0.085, 0.03, 0.9, history=h)
    assert bull.assumptions["revenue_growth"] == pytest.approx(0.10 + gs)
    assert bear.assumptions["revenue_growth"] == pytest.approx(0.10 - gs)
    assert bull.assumptions["fcf_margin"] == pytest.approx(0.05 + ms)
    assert bear.assumptions["fcf_margin"] == pytest.approx(0.05 - ms)
    assert base.assumptions == {"revenue_growth": 0.10, "fcf_margin": 0.05, "wacc": 0.085, "terminal_growth": 0.03}
    assert "own_history_margin_range" in bull.drivers and "own_history_growth_range" in bear.drivers
    assert "historial propio" in bull.description


def test_historial_amplio_se_queda_en_el_techo_y_sin_historial_igual_que_antes():
    wide = {"fcf_margin": {"half_range": 0.20}, "revenue_growth": {"half_range": 0.30}}
    for history in (wide, None, {"fcf_margin": None, "revenue_growth": None}):
        bear, _, bull = mechanical_dcf_scenarios(0.10, 0.05, 0.085, 0.03, 0.9, history=history)
        assert bull.assumptions["revenue_growth"] == pytest.approx(0.18)
        assert bull.assumptions["fcf_margin"] == pytest.approx(0.11)
        assert bear.assumptions["fcf_margin"] == pytest.approx(-0.01)
        assert bull.description == "Mechanical bull: growth +8pp, margin +6pp, WACC -1pp."
        assert bear.description == "Mechanical bear: growth -8pp, margin -6pp, WACC +2pp."


def test_quema_de_caja_sigue_sin_mover_crecimiento_ni_wacc():
    h = {"fcf_margin": {"half_range": 0.02}, "revenue_growth": {"half_range": 0.03}}
    bear, base, bull = mechanical_dcf_scenarios(0.20, -0.10, 0.10, 0.03, 0.5, history=h)
    assert bear.assumptions["revenue_growth"] == bull.assumptions["revenue_growth"] == 0.20
    assert bear.assumptions["fcf_margin"] == pytest.approx(-0.12)
    assert bull.assumptions["fcf_margin"] == pytest.approx(-0.08)


# ---------------- de punta a punta en el motor ----------------


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


def _seed(db, raw, ticker="ESTB"):
    company = Company(
        ticker=ticker,
        name=f"{ticker} test",
        exchange="TEST",
        currency="USD",
        sector="Health Care",
        industry="Managed Health Care",
        company_type="research_candidate",
        valuation_model="unassigned",
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
        fcf = row["operating_cash_flow"] + row["capital_expenditure"]
        _fact(db, company, "free_cash_flow", fcf * M, year)
        _fact(db, company, "fcf_margin", round(fcf / row["revenue"], 6), year, unit="decimal")
        if i:
            _fact(db, company, "revenue_growth", round(row["revenue"] / raw[years[i - 1]]["revenue"] - 1, 6), year, unit="decimal")
        _fact(db, company, "shares_diluted", 100 * M, year, unit="shares")
        _fact(db, company, "net_debt", 0, year)
    db.add(
        CalculatedMetric(
            company_id=company.id, metric="wacc", value=Decimal("0.09"), unit="decimal",
            period=f"{years[-1]}-12-31:FY", fiscal_year=years[-1], status="ok",
            definition_version="WACC_STANDARD_V1", formula="ke*E/(D+E) + kd*(1-t)*D/(D+E)",
        )
    )
    db.add(MarketPrice(company_id=company.id, date=date(2026, 11, 3), close=Decimal("5"), adj_close=Decimal("5"), source="test"))
    db.commit()
    return company


def test_motor_usa_el_historial_propio_y_no_toca_el_base(db):
    company = _seed(db, STABLE)
    engine = StandardDCFEngine()
    out = engine.value(engine.build_context(db, company, 5.0))
    tr = out["trace"]
    hist = tr["scenario_amplitude_history"]
    assert hist["fcf_margin"]["half_range"] < 0.06
    bull = tr["scenarios"]["bull"]["definition"]["assumptions"]
    base = tr["scenarios"]["base"]["definition"]["assumptions"]
    assert bull["fcf_margin"] - base["fcf_margin"] == pytest.approx(hist["fcf_margin"]["half_range"])
    assert bull["revenue_growth"] - base["revenue_growth"] == pytest.approx(hist["revenue_growth"]["half_range"])
    assert out["bear_value"] <= out["base_value"] <= out["bull_value"]
