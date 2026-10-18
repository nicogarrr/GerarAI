"""PR-B: cada input de la tesis lleva etiqueta de procedencia (dato /
derivado / estimacion_llm / supuesto), con metodo y cita. Nada se presenta
como dato de fuente primaria lo que no lo es."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FundamentalModelVersion
from app.services.thesis_provenance import (
    LABEL_DATO,
    LABEL_DERIVADO,
    LABEL_ESTIMACION_LLM,
    LABEL_SUPUESTO,
    build_inputs_provenance,
    inputs_provenance_from_snapshot,
    label_for_assumption,
)
from app.services.thesis_service import ThesisService, latest_inputs_provenance


def test_assumption_label_mapping():
    assert label_for_assumption("financial_facts") == LABEL_DERIVADO
    assert label_for_assumption("calculated_metric") == LABEL_DERIVADO
    assert label_for_assumption("model_policy") == LABEL_SUPUESTO
    assert label_for_assumption("assumption_override") == LABEL_SUPUESTO
    assert label_for_assumption("user_provided") == LABEL_SUPUESTO
    assert label_for_assumption("llm_estimate") == LABEL_ESTIMACION_LLM
    # Sin dato o desconocido: no se etiqueta (pendiente, seccion 21).
    assert label_for_assumption("missing") is None
    assert label_for_assumption(None) is None
    assert label_for_assumption("otra_cosa") is None


def _model() -> dict:
    return {
        "assumptions": {
            "wacc": {
                "value": 0.10,
                "unit": "decimal",
                "source_type": "calculated_metric",
                "basis": "CAPM con beta sectorial",
                "source_fact_ids": [11, 12],
                "confidence": 0.8,
            },
            "terminal_growth": {
                "value": 0.02,
                "unit": "decimal",
                "source_type": "model_policy",
                "basis": "politica conservadora del modelo",
                "source_fact_ids": [],
                "confidence": 1.0,
            },
            "revenue_growth": {
                "value": None,
                "unit": "decimal",
                "source_type": "missing",
                "basis": "",
                "source_fact_ids": [],
                "confidence": 0.0,
            },
        },
        "driver_model": [
            {
                "key": "satellites_on_orbit",
                "driver_type": "kpi",
                "status": "sourced",
                "value": 5.0,
                "unit": "count",
                "confidence": 0.9,
                "source_fact_ids": [42],
                "trace": {"period": "2026-Q2"},
            },
            {"key": "monthly_arpu", "status": "missing"},
        ],
    }


def test_build_inputs_provenance_labels():
    items = {item["key"]: item for item in build_inputs_provenance(_model())}
    assert items["wacc"]["label"] == LABEL_DERIVADO
    assert items["wacc"]["method"] == "CAPM con beta sectorial"
    assert items["wacc"]["source_fact_ids"] == [11, 12]
    assert items["terminal_growth"]["label"] == LABEL_SUPUESTO
    assert items["satellites_on_orbit"]["label"] == LABEL_DATO
    assert "2026-Q2" in items["satellites_on_orbit"]["method"]
    # Lo missing no se etiqueta ni se inventa.
    assert "revenue_growth" not in items
    assert "monthly_arpu" not in items


def test_snapshot_roundtrip():
    items = inputs_provenance_from_snapshot(_model())
    assert {item["key"] for item in items} == {"wacc", "terminal_growth", "satellites_on_orbit"}
    assert inputs_provenance_from_snapshot(None) == []


def test_provenance_markdown_table():
    service = ThesisService()
    text = service._provenance_markdown(build_inputs_provenance(_model()))
    assert "| input | etiqueta | valor | método | cita |" in text
    assert "| wacc | derivado | 0.1 | CAPM con beta sectorial | facts: 11, 12 |" in text
    assert "| terminal_growth | supuesto |" in text
    assert "| satellites_on_orbit | dato | 5 |" in text
    assert "estimacion_llm" in text  # glosario de etiquetas en el header
    assert "revenue_growth" not in text


def test_provenance_markdown_empty_honest():
    assert "Sin inputs etiquetables" in ThesisService()._provenance_markdown([])


def test_render_markdown_includes_provenance_section():
    service = ThesisService()
    md = service._render_markdown(
        Company(
            ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD",
            sector="Telecom", industry="Satellites", company_type="growth",
            valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
        ),
        {},
        {"passed": True, "source_coverage_score": 90, "unsupported_claims": 0},
        {},
        long_term_model=_model(),
        version=2,
        evidence=None,
    )
    assert "## 22. Procedencia de los inputs" in md
    assert "| wacc | derivado |" in md


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_latest_inputs_provenance_readback():
    db = _session()
    company = Company(
        ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD",
        sector="Telecom", industry="Satellites", company_type="growth",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    assert latest_inputs_provenance(db, company.id) is None
    db.add(
        FundamentalModelVersion(
            company_id=company.id,
            version=1,
            engine_version="e1",
            algorithm_version="a1",
            framework_key="space_network",
            horizon_years=5,
            status="ok",
            publishable=True,
            input_fingerprint="a" * 64,
            forecast_fingerprint="a" * 64,
            market_snapshot_fingerprint="a" * 64,
            valuation_snapshot_fingerprint="a" * 64,
            model_snapshot=_model(),
        )
    )
    db.flush()
    items = latest_inputs_provenance(db, company.id)
    # Sin base documentada (ni URL) no se muestra INFERIDO: se omite y queda N/D.
    assert {item["key"] for item in items} == set()
