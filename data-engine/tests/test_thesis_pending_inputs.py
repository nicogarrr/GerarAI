"""La tesis siempre se publica con lo que hay y declara sus datos pendientes
(human-in-the-loop): lo que falta se pide, nunca se inventa."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FundamentalModelVersion
from app.services.thesis_service import ThesisService, latest_missing_inputs


def _company() -> Company:
    return Company(
        ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD",
        sector="Telecom", industry="Satellites", company_type="growth",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )


def test_pendings_markdown_lists_missing_inputs_with_hints():
    service = ThesisService()
    valuation = {"missing_inputs": ["shares_diluted"]}
    long_term_model = {"missing_inputs": ["revenue_history_two_periods", "shares_diluted"]}
    text = service._pendings_markdown(valuation, long_term_model, {})
    assert "revenue_history_two_periods" in text
    assert "shares_diluted" in text
    # Dedup: shares_diluted aparece una sola vez.
    assert text.count("`shares_diluted`") == 1
    # Se pide, nunca se inventa.
    assert "nunca se inventan" in text
    assert "10-K" in text  # hint concreto del input conocido


def test_pendings_markdown_lists_pending_evidence_sources():
    service = ThesisService()
    sources = {
        "filings": {"status": "pending", "source": "SEC EDGAR", "detail": "EDGAR inaccesible"},
        "news": {"status": "ok"},
    }
    text = service._pendings_markdown({}, {}, sources)
    assert "Fuentes de evidencia pendientes" in text
    assert "SEC EDGAR" in text
    assert "EDGAR inaccesible" in text


def test_pendings_markdown_honest_when_nothing_missing():
    service = ThesisService()
    text = service._pendings_markdown({}, {}, {})
    assert "Sin datos pendientes" in text


def test_render_markdown_includes_pendings_section():
    service = ThesisService()
    md = service._render_markdown(
        _company(),
        {"missing_inputs": ["shares_diluted"]},
        {"passed": False, "source_coverage_score": 0, "unsupported_claims": 0},
        {},
        long_term_model={"missing_inputs": ["traceable_wacc"]},
        version=1,
        evidence=None,
    )
    assert "## 21. Datos pendientes" in md
    assert "shares_diluted" in md
    assert "traceable_wacc" in md


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_latest_missing_inputs_none_without_model():
    db = _session()
    company = _company()
    db.add(company)
    db.flush()
    assert latest_missing_inputs(db, company.id) is None


def test_latest_missing_inputs_reads_model_snapshot():
    db = _session()
    company = _company()
    db.add(company)
    db.flush()
    db.add(
        FundamentalModelVersion(
            company_id=company.id,
            version=1,
            engine_version="e1",
            algorithm_version="a1",
            framework_key="space_network",
            horizon_years=5,
            status="missing_mandatory_drivers",
            publishable=False,
            input_fingerprint="f" * 64,
            forecast_fingerprint="f" * 64,
            market_snapshot_fingerprint="f" * 64,
            valuation_snapshot_fingerprint="f" * 64,
            model_snapshot={
                "missing_inputs": ["revenue_history_two_periods", "traceable_wacc"],
                "missing_mandatory_drivers": ["satellites_on_orbit", "traceable_wacc"],
            },
        )
    )
    db.flush()
    missing = latest_missing_inputs(db, company.id)
    assert missing == ["revenue_history_two_periods", "satellites_on_orbit", "traceable_wacc"]
