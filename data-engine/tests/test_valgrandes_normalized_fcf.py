"""Empresas grandes con datos completos siempre tienen valor razonable.

Encargo de Nico (3-nov-2026, 21:14): «Es imposible no poder valorar empresas
tan grandes y con tantos datos como Amazon y Palantir». Los historiales de
abajo son los hechos SEC de AMZN y PLTR leídos en prod ese día (millones de
US$, FY2019–FY2025); los tests prueban que:

* AMZN (capex de IA 131.819 M vs amortización 65.756 M) recibe un valor con
  capex normalizado y etiqueta «estimado, capex normalizado» en vez de los
  26 US$ del DCF con el margen hundido del último año;
* PLTR (crece al 56 %) recibe DCF multietapa y un DCF inverso que dice qué
  crecimiento descuenta el precio, aunque el valor quede lejos del precio;
* la guarda 0,2x–5x avisa (nunca borra) y viaja con el rango por múltiplos;
* la etiqueta llega al resultado que consumen API, tesis y UI.
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
from app.valuation.normalized_fcf import (
    CAPEX_LABEL,
    MULTISTAGE_LABEL,
    ProjectionPlan,
    capex_normalization,
    plausibility_warning,
    revenue_cagr,
    run_path_dcf,
)

M = 1_000_000

# Hechos SEC leídos en prod el 3-nov-2026 (millones de US$).
AMZN = {
    2019: dict(revenue=280522, operating_cash_flow=38514, capital_expenditure=-16861, depreciation_amortization=21789),
    2020: dict(revenue=386064, operating_cash_flow=66064, capital_expenditure=-40140, depreciation_amortization=25180),
    2021: dict(revenue=469822, operating_cash_flow=46327, capital_expenditure=-61053, depreciation_amortization=34433),
    2022: dict(revenue=513983, operating_cash_flow=46752, capital_expenditure=-63645, depreciation_amortization=41921),
    2023: dict(revenue=574785, operating_cash_flow=84946, capital_expenditure=-52729, depreciation_amortization=48663),
    2024: dict(revenue=637959, operating_cash_flow=115877, capital_expenditure=-82999, depreciation_amortization=52795),
    2025: dict(revenue=716924, operating_cash_flow=139514, capital_expenditure=-131819, depreciation_amortization=65756),
}
PLTR = {
    2019: dict(revenue=742.6, operating_cash_flow=-165.2, capital_expenditure=-13.1, depreciation_amortization=12.3),
    2020: dict(revenue=1092.7, operating_cash_flow=-296.6, capital_expenditure=-12.2, depreciation_amortization=13.9),
    2021: dict(revenue=1541.9, operating_cash_flow=333.9, capital_expenditure=-12.6, depreciation_amortization=14.9),
    2022: dict(revenue=1905.9, operating_cash_flow=223.7, capital_expenditure=-40.0, depreciation_amortization=22.5),
    2023: dict(revenue=2225.0, operating_cash_flow=712.2, capital_expenditure=15.1, depreciation_amortization=33.4),
    2024: dict(revenue=2865.5, operating_cash_flow=1153.9, capital_expenditure=12.6, depreciation_amortization=31.6),
    2025: dict(revenue=4475.4, operating_cash_flow=2134.5, capital_expenditure=33.9, depreciation_amortization=26.1),
}


class _F:
    def __init__(self, value, unit="USD", fid=None):
        self.value, self.unit, self.id = value, unit, fid


def _history(raw):
    return {year: {k: _F(v * M) for k, v in row.items()} for year, row in raw.items()}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker):
    row = Company(
        ticker=ticker, name=f"{ticker} test", exchange="TEST", currency="USD", sector="Tech",
        industry="Internet", company_type="standard", valuation_model="standard_dcf",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(row)
    db.flush()
    return row


def _fact(db, company, metric, value, year, unit="USD"):
    db.add(
        FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
            period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY",
            source_type="SEC", is_reported=True, confidence=Decimal("0.90"),
        )
    )


def _seed(db, ticker, raw, *, shares, net_debt, price, wacc):
    company = _company(db, ticker)
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
        _fact(db, company, "shares_diluted", shares, year, unit="shares")
        _fact(db, company, "net_debt", net_debt, year)
    db.add(
        CalculatedMetric(
            company_id=company.id, metric="wacc", value=Decimal(str(wacc)), unit="decimal",
            period=f"{years[-1]}-12-31:FY", fiscal_year=years[-1], status="ok",
            definition_version="WACC_STANDARD_V1", formula="ke*E/(D+E) + kd*(1-t)*D/(D+E)",
        )
    )
    db.add(MarketPrice(company_id=company.id, date=date(2026, 11, 3), close=Decimal(str(price)),
                       adj_close=Decimal(str(price)), source="test"))
    db.commit()
    return company


def test_capex_normalization_amzn_like_history():
    result = capex_normalization(_history(AMZN), 0.010733)
    assert result["applied"] is True
    assert result["label"] == CAPEX_LABEL
    latest = result["latest"]
    assert latest["growth_capex"] == pytest.approx((131819 - 65756) * M)
    assert latest["maintenance_capex"] == pytest.approx(65756 * M)
    # Media FY2019–FY2025 de (flujo operativo − min(capex, amortización)) / ingresos.
    expected = sum(
        (r["operating_cash_flow"] - min(abs(r["capital_expenditure"]), r["depreciation_amortization"])) / r["revenue"]
        for r in AMZN.values()
    ) / 7
    assert result["target_margin"] == pytest.approx(expected)
    assert result["midcycle_years"] == list(range(2025, 2018, -1))
    assert result["initial_margin"] == pytest.approx(0.010733)
    assert "capex normalizado" in result["note_es"].lower() or "Capex normalizado" in result["note_es"]


def test_capex_normalization_does_not_fire_without_growth_capex():
    result = capex_normalization(_history(PLTR), 2100.6 / 4475.4)
    assert result["applied"] is False
    assert result["reason"]


def test_path_dcf_matches_hand_calculation():
    plan = ProjectionPlan(growth_fade=True, margin_start=0.01)
    growth_path = plan.growth_path(0.12, 0.03)
    assert growth_path[:5] == [0.12] * 5
    assert growth_path[-1] == pytest.approx(0.03)
    margin_path = plan.margin_path(0.07, 0.07)
    assert margin_path[0] == pytest.approx(0.01 + 0.06 / 5)
    assert margin_path[4:] == pytest.approx([0.07] * 6)
    result = run_path_dcf(revenue=1000.0, growth_path=growth_path, margin_path=margin_path, wacc=0.09,
                          terminal_growth=0.03, net_debt=0.0, shares_outstanding=10.0)
    revenue, pv = 1000.0, 0.0
    for year, (g, m) in enumerate(zip(growth_path, margin_path), start=1):
        revenue *= 1 + g
        pv += revenue * m / 1.09 ** year
    last_fcf = revenue * margin_path[-1]
    pv += last_fcf * 1.03 / 0.06 / 1.09 ** 10
    assert result.value_per_share == pytest.approx(pv / 10.0)


def test_amzn_like_gets_labeled_fair_value_instead_of_crushed_margin(db):
    company = _seed(db, "AMZNX", AMZN, shares=10_827 * M, net_debt=-5_233 * M, price=251.36, wacc=0.11141566)
    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 251.36))
    assert result["status"] == "ok" and result["publishable"] is True
    # Prod hoy (margen del último año, 5 años planos): 26,29 US$.
    assert result["expected_value"] > 60.0
    assert CAPEX_LABEL in result["valuation_label"]
    assert MULTISTAGE_LABEL in result["valuation_label"]
    projection = result["trace"]["projection"]
    assert projection["capex_normalization"]["applied"] is True
    assert projection["years"] == 10
    assert projection["normalized_fcf_per_share"] == pytest.approx((139514 - 65756) * M / (10_827 * M))
    assert any("Capex normalizado" in note for note in result["valuation_notes"])
    assert result["bear_value"] is None or result["bear_value"] <= result["base_value"] <= result["bull_value"]
    reverse = result["reverse_dcf"]
    assert reverse["trace"]["method"] == "planned_reverse_dcf"
    assert "descuenta" in reverse["explanation_es"] or "justifica" in reverse["explanation_es"]
    assert reverse["required_fcf_margin"] is not None


def test_pltr_like_multistage_with_implied_growth_explanation(db):
    company = _seed(db, "PLTRX", PLTR, shares=2_565.2 * M, net_debt=-6_000 * M, price=178.34, wacc=0.1204)
    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 178.34))
    assert result["status"] == "ok" and result["expected_value"] > 0
    assert result["valuation_label"] == MULTISTAGE_LABEL
    projection = result["trace"]["projection"]
    assert projection["stage1_growth_basis"] == "revenue_cagr_3y"
    assert projection["stage1_growth"] == pytest.approx((4475.4 / 1905.9) ** (1 / 3) - 1)
    reverse = result["reverse_dcf"]
    assert reverse["status"] == "ok"
    assert reverse["required_revenue_growth"] > projection["stage1_growth"]
    assert "El precio de 178,34 descuenta un crecimiento" in reverse["explanation_es"]


def test_plausibility_band_warns_never_wipes(db):
    assert plausibility_warning(50.0, 100.0) is None
    warning = plausibility_warning(10.0, 100.0)
    assert warning["code"] == "fair_value_far_from_price"
    assert "0,10 veces" in warning["message_es"]
    # En el motor: el valor sigue publicado y el aviso va al lado.
    company = _seed(db, "FARX", AMZN, shares=10_827 * M, net_debt=-5_233 * M, price=2_000.0, wacc=0.11141566)
    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 2_000.0))
    assert result["expected_value"] is not None and result["expected_value"] > 0
    assert result["plausibility_warning"]["ratio_to_price"] < 0.2
    assert result["trace"]["plausibility_warning"] == result["plausibility_warning"]


def test_flat_case_unchanged_without_history(db):
    """Un FY y crecimiento < 10 %: ni etiqueta ni campos nuevos."""
    company = _company(db, "FLAT")
    for metric, value, unit in (("revenue", 1000 * M, "USD"), ("free_cash_flow", 150 * M, "USD"),
                                ("revenue_growth", 0.05, "decimal"), ("shares_diluted", 100 * M, "shares"),
                                ("net_debt", 0, "USD")):
        _fact(db, company, metric, value, 2025, unit=unit)
    db.commit()
    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 20.0))
    assert "valuation_label" not in result
    assert "projection" not in result["trace"]


def test_revenue_cagr_uses_three_fiscal_years():
    cagr = revenue_cagr(_history(PLTR), 3)
    assert cagr["from_year"] == 2022 and cagr["to_year"] == 2025
    assert cagr["value"] == pytest.approx((4475.4 / 1905.9) ** (1 / 3) - 1)



def test_fair_value_range_combines_dcf_and_multiples():
    from app.services.valuation_service import _fair_value_range, _multiple_screens

    screens = _multiple_screens(
        {
            "pe": {"status": "ok", "implied_value_per_share": {"p25": 202.8, "median": 315.5, "p75": 585.3},
                   "peer_stats": {"median": 44.0, "peer_set_size": 8}},
            "p_to_fcf": {"status": "ok", "implied_value_per_share": {"p25": 20.0, "median": 30.0, "p75": 40.0},
                         "peer_stats": {"median": 40.0, "peer_set_size": 6}},
            "ev_to_sales": {"status": "no_peer_multiple", "implied_value_per_share": {"median": None}},
        },
        1.0,
    )
    assert set(screens) == {"pe", "p_to_fcf"}
    result = {
        "expected_value": 85.0,
        "valuation_label": CAPEX_LABEL,
        "trace": {"projection": {"normalized_fcf_per_share": 6.81}},
    }
    fair_range = _fair_value_range(result, {"screens": screens, "value_currency": "USD", "scale_factor_to_listing": 1.0})
    methods = {item["method"]: item["value"] for item in fair_range["components"]}
    assert methods["dcf"] == 85.0
    assert methods["pe"] == 315.5
    # Mediana P/FCF de los peers (40x) sobre el FCF con capex de mantenimiento.
    assert methods["p_to_fcf_normalized"] == pytest.approx(6.81 * 40.0)
    assert fair_range["low"] == 30.0 and fair_range["high"] == 315.5
    assert "capex normalizado" in fair_range["components"][0]["label"]
    # Un solo método no es contraste.
    assert _fair_value_range({"expected_value": 85.0, "trace": {}}, {"screens": {}}) is None


def test_thesis_text_carries_label_warning_range_and_implied_growth():
    from app.services.thesis_service import valuation_method_lines

    lines = valuation_method_lines(
        {
            "valuation_label": CAPEX_LABEL,
            "valuation_notes": ["Capex normalizado: nota"],
            "plausibility_warning": {"message_es": "El valor del DCF es 0,10 veces el precio"},
            "fair_value_range": {"low": 85.0, "high": 315.5, "currency": "USD",
                                 "components": [{"label": "DCF", "value": 85.0}, {"label": "PER", "value": 315.5}]},
            "reverse_dcf": {"explanation_es": "El precio de 251,36 descuenta un crecimiento"},
        }
    )
    text = "\n".join(lines)
    assert "estimado, capex normalizado" in text
    assert "Aviso: El valor del DCF" in text
    assert "Rango de contraste" in text
    assert "Qué descuenta el precio" in text
    assert valuation_method_lines({"status": "ok"}) == []



def test_fair_value_reading_carries_method_label():
    from datetime import date as _date

    from app.services.fair_value_service import Candidate, _method_label, _reading

    payload = {"expected_value": 108.4, "valuation_label": CAPEX_LABEL}
    candidate = Candidate(value=108.4, as_of=_date(2026, 11, 3), publishable=True,
                          method_label=_method_label(payload))
    reading = _reading("motor", candidate, stale=False, rule="motor")
    assert reading["label"] == f"Motor de valoración · {CAPEX_LABEL}"
    assert reading["method_label"] == CAPEX_LABEL
    assert _method_label({"expected_value": 1.0}) is None


def test_valuation_api_schema_keeps_labels():
    """El response_model de GET /api/valuation/{ticker} filtraba los campos nuevos."""
    from app.schemas.api import ValuationResponse

    out = ValuationResponse(
        ticker="AMZN", model_type="dcf", valuation_label=CAPEX_LABEL, valuation_notes=["nota"],
        plausibility_warning={"code": "fair_value_far_from_price"},
        fair_value_range={"low": 85.0, "high": 315.5},
        reverse_dcf={"explanation_es": "El precio de 251,36 descuenta"},
    ).model_dump()
    assert out["valuation_label"] == CAPEX_LABEL
    assert out["fair_value_range"]["high"] == 315.5
    assert out["reverse_dcf"]["explanation_es"].startswith("El precio")
    assert ValuationResponse(ticker="X", model_type="dcf").model_dump()["valuation_label"] is None


def test_growth_semantics_separates_observed_applied_and_market_implied(db):
    company = _seed(db, "GROWTHX", PLTR, shares=2_565.2 * M, net_debt=-6_000 * M,
                    price=178.34, wacc=0.1204)
    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 178.34))
    semantics = result["trace"]["growth_semantics"]
    applied = result["trace"]["scenarios"]["base"]["trace"]["inputs"]
    assert semantics["applied_stage1_revenue_growth"] == applied["growth_path"][0]
    assert semantics["applied_growth_path"] == applied["growth_path"]
    assert semantics["applied_growth_basis"] == "revenue_cagr_3y"
    assert semantics["historical_revenue_cagr"]["value"] == applied["growth_path"][0]
    assert semantics["market_implied_revenue_growth"] == result["reverse_dcf"]["required_revenue_growth"]
    assert semantics["market_implied_is_forecast"] is False
    assert semantics["observed_latest_revenue_growth"] != semantics["market_implied_revenue_growth"]
