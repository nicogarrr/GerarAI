"""El modelo de valoración declarado (company.valuation_model) y el motor que
de verdad corre no pueden divergir en silencio.

TSLA en prod (4-nov-2026): declarado «scenario_auto_energy_fsd» (maestro),
resuelto standard_dcf. Ningún motor implementa ese método de escenarios (el
de pre_revenue es para empresas sin ingresos, con dilución por financiación),
así que el DCF estándar es el respaldo correcto; pero la traza, el modelo
guardado y la tesis seguían diciendo «scenario_auto_energy_fsd» como si ese
método hubiera corrido. Lo mismo KRKNF («defense_backlog_scenario_model»).
Ahora el resultado lo declara: modelo declarado, motor resuelto y motivo.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.services.valuation_service import ValuationService
from app.valuation.engines.registry import declared_engine_fallback
from tests.test_valgrandes_normalized_fcf import AMZN, M, _seed


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _co(model: str, **kw) -> SimpleNamespace:
    base = dict(ticker="XSCN", valuation_model=model, factor_tags=[],
                company_type="research_candidate", industry="Automobiles")
    base.update(kw)
    return SimpleNamespace(**base)


def test_scenario_model_without_engine_runs_dcf_and_says_why(db):
    company = _seed(db, "XSCN", AMZN, shares=10_000 * M, net_debt=-5_000 * M, price=150.0, wacc=0.09)
    company.valuation_model = "scenario_auto_energy_fsd"
    company.company_type = "auto_energy_optionality"
    db.commit()
    result = ValuationService().value_company(db, company)
    trace = result["trace"]
    assert trace["resolved_engine"] == "standard_dcf"
    assert trace["declared_model"] == "scenario_auto_energy_fsd"
    fallback = trace["engine_fallback"]
    assert fallback["reason"] == "declared_method_without_engine"
    assert fallback["declared_method"] == "scenario_auto_energy_fsd"
    assert fallback["resolved_engine"] == "standard_dcf"


@pytest.mark.parametrize(
    ("model", "kw"),
    [
        ("dcf+reverse_dcf+ai_capex_sensitivity", {}),  # MSFT/META: un DCF corre un DCF
        ("software_dcf+rule_of_40_context", {}),  # PLTR
        ("sotp+asset_management_multiple", {"company_type": "asset_manager_holding"}),  # BN → holding
        ("probability_weighted_scenarios+dilution", {"factor_tags": ["pre_fcf"]}),  # ASTS
        ("commodity_sensitivity+dcf", {"company_type": "uranium_mining"}),  # CCJ
        ("nav_rough+dilution_risk", {"company_type": "mining_pre_revenue"}),  # HYMC → commodity
        ("unassigned", {}),  # stub: no hay modelo declarado
        ("", {}),
    ],
)
def test_declared_model_served_by_its_engine_records_no_fallback(model, kw):
    assert declared_engine_fallback(_co(model, **kw)) is None


@pytest.mark.parametrize(
    ("model", "kw", "reason", "engine"),
    [
        ("scenario_auto_energy_fsd", {}, "declared_method_without_engine", "standard_dcf"),
        ("defense_backlog_scenario_model", {}, "declared_method_without_engine", "standard_dcf"),
        # Declara un DCF pero la industria lo manda al motor bancario: corre
        # otro motor por clasificación, y queda dicho.
        ("dcf+reverse_dcf", {"industry": "Banks - Regional"}, "overridden_by_classification", "bank"),
    ],
)
def test_declared_model_not_served_names_the_reason(model, kw, reason, engine):
    fallback = declared_engine_fallback(_co(model, **kw))
    assert fallback is not None
    assert fallback["reason"] == reason
    assert fallback["resolved_engine"] == engine
    assert fallback["declared_model"] == model
