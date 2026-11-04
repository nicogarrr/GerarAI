"""Motor de escenarios ponderados para empresas con ingresos.

TSLA («scenario_auto_energy_fsd»), KRKNF («defense_backlog_scenario_model») y
NBIS («capacity_capex_utilization_model») declaraban en el maestro un método
de escenarios o de capacidad que ningún motor implementaba: corría el DCF
estándar (o pre_revenue) y la traza lo decía como respaldo (#4542). Nico
(4-nov-2026): «sí, construye todo lo que haga falta». Ahora la familia de
métodos de escenarios/capacidad/cartera de pedidos (por el método declarado,
nunca por ticker) corre el motor ``scenario``:

- escenarios declarados EN DATOS (``app/data/valuation_scenarios.py``) con
  probabilidad y método por escenario (DCF con las mismas piezas del DCF
  estándar, o múltiplo sobre una métrica futura);
- sin datos, un juego por defecto bajista/base/alcista derivado de las
  entradas de la propia empresa (25/50/25, WACC y g terminal intactos);
- con datos inválidos o sin ingresos/DCF base, respaldo al motor actual con
  el motivo en ``trace.engine_fallback``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.data import valuation_scenarios
from app.models.entities import Base
from app.services.valuation_service import ValuationService
from app.valuation.engines.registry import declared_engine_fallback, resolve_engine_key
from tests.test_valgrandes_normalized_fcf import M, _seed

# Empresa madura sintética: crece ~5 %, capex por debajo de la amortización
# (sin normalización de capex ni DCF multietapa: DCF plano de 5 años).
MATURE = {
    2022: dict(revenue=10000, operating_cash_flow=1500, capital_expenditure=-400, depreciation_amortization=500),
    2023: dict(revenue=10500, operating_cash_flow=1575, capital_expenditure=-420, depreciation_amortization=525),
    2024: dict(revenue=11025, operating_cash_flow=1654, capital_expenditure=-441, depreciation_amortization=551),
    2025: dict(revenue=11576, operating_cash_flow=1736, capital_expenditure=-463, depreciation_amortization=579),
}
SHARES = 1_000 * M
NET_DEBT = 2_000 * M
WACC = 0.09


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _company(db, model: str, ticker: str = "XSCN", **kw):
    company = _seed(db, ticker, MATURE, shares=SHARES, net_debt=NET_DEBT, price=20.0, wacc=WACC)
    company.valuation_model = model
    company.company_type = kw.pop("company_type", "auto_energy_optionality")
    for key, value in kw.items():
        setattr(company, key, value)
    db.commit()
    return company


def _co(model: str, **kw) -> SimpleNamespace:
    base = dict(ticker="XSCN", valuation_model=model, factor_tags=[],
                company_type="research_candidate", industry="Automobiles")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize(
    ("model", "kw"),
    [
        ("scenario_auto_energy_fsd", {}),  # TSLA
        ("defense_backlog_scenario_model", {}),  # KRKNF
        # NBIS: la etiqueta «speculative» no gana al método declarado; si el
        # DCF base no es posible, el motor vuelve a pre_revenue con motivo.
        ("capacity_capex_utilization_model", {"factor_tags": ["ai", "infra", "speculative"]}),
    ],
)
def test_declared_scenario_family_routes_to_scenario_engine(model, kw):
    assert resolve_engine_key(_co(model, **kw)) == "scenario"
    assert declared_engine_fallback(_co(model, **kw)) is None


@pytest.mark.parametrize(
    ("model", "kw", "engine"),
    [
        ("speculative_scenario_model", {"factor_tags": ["speculative"]}, "pre_revenue"),
        ("probability_weighted_scenarios+dilution", {"factor_tags": ["pre_fcf"]}, "pre_revenue"),
        ("sotp+backlog_capex_scenario", {}, "sotp"),
        ("dcf+reverse_dcf+ai_capex_sensitivity", {}, "standard_dcf"),
        # Sin ingresos no hay escenarios de negocio: manda el tipo pre-ingresos.
        ("scenario_auto_energy_fsd", {"company_type": "pre_revenue_biotech"}, "pre_revenue"),
    ],
)
def test_other_methods_keep_their_engine(model, kw, engine):
    assert resolve_engine_key(_co(model, **kw)) == engine


def test_scenario_model_runs_default_scenarios_and_weights_them(db):
    company = _company(db, "scenario_auto_energy_fsd")
    result = ValuationService().value_company(db, company)
    trace = result["trace"]
    assert trace["engine"] == "scenario"
    assert trace["resolved_engine"] == "scenario"
    assert "engine_fallback" not in trace
    scenario_set = trace["scenario_set"]
    assert scenario_set["source"] == "default_derived"
    names = [s["name"] for s in scenario_set["scenarios"]]
    assert names == ["bear", "base", "bull"]
    probs = [s["probability"] for s in scenario_set["scenarios"]]
    assert probs == pytest.approx([0.25, 0.50, 0.25])
    values = [s["value_per_share"] for s in scenario_set["scenarios"]]
    assert values[0] < values[1] < values[2]
    assert result["expected_value"] == pytest.approx(sum(p * v for p, v in zip(probs, values, strict=True)))
    assert result["bear_value"] == pytest.approx(values[0])
    assert result["base_value"] == pytest.approx(values[1])
    assert result["bull_value"] == pytest.approx(values[2])
    # El base es exactamente el base del DCF estándar (mismas entradas).
    plain = ValuationService().value_company(db, _company(db, "dcf+reverse_dcf", ticker="XDCF"))
    assert plain["trace"]["engine"] == "standard_dcf"
    assert result["base_value"] == pytest.approx(plain["base_value"])
    # WACC y g terminal intactos en los tres escenarios.
    for item in scenario_set["scenarios"]:
        assert item["assumptions"]["wacc"] == pytest.approx(plain["trace"]["wacc"])


def test_declared_scenarios_weighted_value_equals_hand_sum(db, monkeypatch):
    monkeypatch.setitem(
        valuation_scenarios.VALUATION_SCENARIOS,
        "XSCN",
        {
            "source": "test",
            "scenarios": [
                {"name": "core", "probability": 0.6, "method": "dcf", "revenue_growth": 0.05, "fcf_margin": 0.11},
                {"name": "bust", "probability": 0.3, "method": "dcf", "revenue_growth": 0.0, "fcf_margin": 0.04},
                {"name": "platform", "probability": 0.1, "method": "forward_multiple", "metric": "revenue",
                 "multiple": 4.0, "year": 5, "revenue_growth": 0.25, "fcf_margin": 0.15},
            ],
        },
    )
    company = _company(db, "scenario_auto_energy_fsd")
    result = ValuationService().value_company(db, company)
    trace = result["trace"]
    assert trace["engine"] == "scenario"
    assert trace["scenario_set"]["source"] == "declared"
    by_name = {s["name"]: s for s in trace["scenario_set"]["scenarios"]}
    assert set(by_name) == {"core", "bust", "platform"}

    # Múltiplo futuro a mano: FCF de los años 1..5 + EV/ventas 4x del año 5,
    # descontados al WACC, menos deuda neta, entre acciones.
    revenue = MATURE[2025]["revenue"] * M
    wacc = trace["wacc"]
    pv = 0.0
    rev = revenue
    for year in range(1, 6):
        rev *= 1.25
        pv += rev * 0.15 / (1 + wacc) ** year
    pv += 4.0 * rev / (1 + wacc) ** 5
    platform = (pv - NET_DEBT) / SHARES
    assert by_name["platform"]["value_per_share"] == pytest.approx(platform, rel=1e-9)

    expected = sum(by_name[n]["probability"] * by_name[n]["value_per_share"] for n in by_name)
    assert result["expected_value"] == pytest.approx(expected)
    assert result["bear_value"] == pytest.approx(by_name["bust"]["value_per_share"])
    assert result["bull_value"] == pytest.approx(max(s["value_per_share"] for s in by_name.values()))
    # Sin escenario llamado «base», el base es el más probable.
    assert result["base_value"] == pytest.approx(by_name["core"]["value_per_share"])


@pytest.mark.parametrize(
    "bad",
    [
        # Las probabilidades no suman 1.
        [{"name": "a", "probability": 0.5, "method": "dcf", "revenue_growth": 0.05, "fcf_margin": 0.1},
         {"name": "b", "probability": 0.3, "method": "dcf", "revenue_growth": 0.0, "fcf_margin": 0.05}],
        # Método desconocido.
        [{"name": "a", "probability": 1.0, "method": "vibes"}],
        # Múltiplo no positivo.
        [{"name": "a", "probability": 1.0, "method": "forward_multiple", "metric": "revenue", "multiple": 0, "year": 5}],
        # Un escenario no puede tocar el WACC (lo decide otro carril).
        [{"name": "a", "probability": 1.0, "method": "dcf", "wacc": 0.05}],
        # Crecimiento por encima del techo general (0.45): los escenarios
        # hipercrecimiento publicados (p. ej. ARK TSLA 2031, CAGR 52-60 %) no
        # entran sin cambiar el tope, que es decisión general, no de un ticker.
        [{"name": "a", "probability": 1.0, "method": "dcf", "revenue_growth": 0.60, "fcf_margin": 0.1}],
        # Margen por encima del techo general (0.50).
        [{"name": "a", "probability": 1.0, "method": "dcf", "revenue_growth": 0.05, "fcf_margin": 0.55}],
    ],
)
def test_invalid_declared_scenarios_fall_back_with_reason(db, monkeypatch, bad):
    monkeypatch.setitem(valuation_scenarios.VALUATION_SCENARIOS, "XSCN", {"source": "test", "scenarios": bad})
    company = _company(db, "scenario_auto_energy_fsd")
    result = ValuationService().value_company(db, company)
    trace = result["trace"]
    assert trace["engine"] == "standard_dcf"
    assert trace["resolved_engine"] == "standard_dcf"
    fallback = trace["engine_fallback"]
    assert fallback["reason"] == "scenario_inputs_invalid"
    assert fallback["resolved_engine"] == "standard_dcf"
    assert fallback["declared_model"] == "scenario_auto_energy_fsd"
    assert fallback["detail"]
    plain = ValuationService().value_company(db, _company(db, "dcf+reverse_dcf", ticker="XDCF"))
    assert result["expected_value"] == pytest.approx(plain["expected_value"])


def test_cash_burner_falls_back_to_classification_engine_with_reason(db):
    burner = {
        2023: dict(revenue=1000, operating_cash_flow=-300, capital_expenditure=-500, depreciation_amortization=50),
        2024: dict(revenue=1500, operating_cash_flow=-200, capital_expenditure=-700, depreciation_amortization=80),
        2025: dict(revenue=2200, operating_cash_flow=-100, capital_expenditure=-900, depreciation_amortization=120),
    }
    company = _seed(db, "XBRN", burner, shares=SHARES, net_debt=-500 * M, price=20.0, wacc=0.11)
    company.valuation_model = "capacity_capex_utilization_model"
    company.company_type = "ai_infra_capacity"
    company.factor_tags = ["ai", "infra", "speculative"]
    db.commit()
    result = ValuationService().value_company(db, company)
    trace = result["trace"]
    assert trace["engine"] == "pre_revenue"
    fallback = trace["engine_fallback"]
    assert fallback["reason"] == "scenario_base_dcf_unavailable"
    assert fallback["resolved_engine"] == "pre_revenue"


def test_normalized_margin_does_not_turn_a_cash_burner_into_scenarios(db):
    """NBIS en prod: FCF reportado negativo por capex de crecimiento; solo el
    margen normalizado (capex de mantenimiento) lo haría positivo. pre_revenue
    se niega a sustituir el margen reportado; los escenarios tampoco lo hacen."""
    capex_heavy = {
        2022: dict(revenue=1000, operating_cash_flow=200, capital_expenditure=-350, depreciation_amortization=80),
        2023: dict(revenue=1300, operating_cash_flow=260, capital_expenditure=-455, depreciation_amortization=104),
        2024: dict(revenue=1690, operating_cash_flow=338, capital_expenditure=-592, depreciation_amortization=135),
        2025: dict(revenue=2197, operating_cash_flow=439, capital_expenditure=-769, depreciation_amortization=176),
    }
    company = _seed(db, "XCPX", capex_heavy, shares=SHARES, net_debt=-500 * M, price=20.0, wacc=0.10)
    company.valuation_model = "capacity_capex_utilization_model"
    company.company_type = "ai_infra_capacity"
    company.factor_tags = ["ai", "infra", "speculative"]
    db.commit()
    result = ValuationService().value_company(db, company)
    trace = result["trace"]
    assert "scenario_set" not in trace
    fallback = trace["engine_fallback"]
    assert fallback["reason"] == "scenario_base_dcf_unavailable"
    assert fallback["resolved_engine"] == "pre_revenue"
    assert "normalizado" in fallback["detail"]
    assert trace["engine"] == "pre_revenue"
