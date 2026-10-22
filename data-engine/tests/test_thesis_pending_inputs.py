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

def test_pendings_markdown_no_pide_presente_excluido_con_key_cubierta():
    """Contradicción 0presente→faltante: la key «no_revenue_reported» (missing)
    y la métrica «revenue» (excluded) viven en espacios distintos; la resta
    literal nunca las emparejaba y la tarjeta pedía ingresos como ausentes
    estando reportados (0) — exactamente lo que el cuerpo declara presente."""
    service = ThesisService()
    valuation = {
        "missing_inputs": ["no_revenue_reported", "normalized_fcf_margin"],
        "excluded_inputs": [
            {"metric": "revenue", "reason": "present_not_usable", "detail": "ingresos reportados 0 en el periodo ancla", "available_period": "2023-12-31:FY", "anchor_period": "2023-12-31:FY"}
        ],
    }
    text = service._pendings_markdown(valuation, {}, {})
    assert "no_revenue_reported" not in text
    assert "normalized_fcf_margin" in text


def test_missing_split_presentes_con_key_cubierta():
    service = ThesisService()
    valuation = {
        "status": "insufficient_data",
        "missing_inputs": ["no_revenue_reported", "normalized_fcf_margin"],
        "trace": {"engine": "dcf"},
    }
    excluded = [{"metric": "revenue", "reason": "present_not_usable", "detail": "ingresos reportados 0 en el periodo ancla", "available_period": "2023-12-31:FY", "anchor_period": "2023-12-31:FY"}]
    md = service._valuation_markdown(valuation, excluded_present=excluded)
    faltan = md.split("Presentes pero no utilizables:")[0]
    presentes = md.split("Presentes pero no utilizables:")[1]
    assert "no_revenue_reported" not in faltan
    assert "ingresos reportados 0 en el periodo ancla" in presentes
    assert "presente, no utilizable" in presentes


def test_card_summary_no_pide_revenue_presente_excluido():
    service = ThesisService()
    valuation = {
        "status": "insufficient_data",
        "missing_inputs": ["no_revenue_reported", "normalized_fcf_margin"],
        "excluded_inputs": [
            {"metric": "revenue", "reason": "present_not_usable", "detail": "ingresos reportados 0 en el periodo ancla", "available_period": "2023-12-31:FY", "anchor_period": "2023-12-31:FY"}
        ],
    }
    summary = service._card_summary(_company(), valuation, "hipótesis", None, None)
    assert "no_revenue_reported" not in summary
    assert "Otros datos ya los tenemos" in summary  # nota de presentes, no petición
    assert "no se pide como dato ausente" in summary


def test_latest_missing_inputs_filtra_cubierta_por_excluido_persistido():
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
            status="insufficient_data",
            publishable=False,
            input_fingerprint="f" * 64,
            forecast_fingerprint="f" * 64,
            market_snapshot_fingerprint="f" * 64,
            valuation_snapshot_fingerprint="f" * 64,
            model_snapshot={
                "missing_inputs": ["no_revenue_reported", "traceable_wacc"],
                "missing_mandatory_drivers": [],
                "valuation": {
                    "excluded_inputs": [
                        {"metric": "revenue", "reason": "present_not_usable", "detail": "ingresos reportados 0 en el periodo ancla", "available_period": "2023-12-31:FY", "anchor_period": "2023-12-31:FY"}
                    ]
                },
            },
        )
    )
    db.flush()
    assert latest_missing_inputs(db, company.id) == ["traceable_wacc"]


def test_latest_missing_inputs_sin_excluded_persistido_inalterado():
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
            status="insufficient_data",
            publishable=False,
            input_fingerprint="f" * 64,
            forecast_fingerprint="f" * 64,
            market_snapshot_fingerprint="f" * 64,
            valuation_snapshot_fingerprint="f" * 64,
            model_snapshot={"missing_inputs": ["no_revenue_reported"], "missing_mandatory_drivers": []},
        )
    )
    db.flush()
    assert latest_missing_inputs(db, company.id) == ["no_revenue_reported"]


def test_guard_literales_missing_cubiertos_existen_en_long_term_model():
    """Sincronía: si long_term_model_service renombra la key cubierta, el
    mapping _EXCLUDED_COVERS_MISSING queda huérfano y este test lo grita."""
    import inspect

    from app.services import long_term_model_service
    from app.services.thesis_service import _EXCLUDED_COVERS_MISSING

    source = inspect.getsource(long_term_model_service)
    for keys in _EXCLUDED_COVERS_MISSING.values():
        for key in keys:
            assert f'"{key}"' in source
