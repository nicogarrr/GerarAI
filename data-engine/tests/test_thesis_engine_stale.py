"""Señal engine_stale: el motor de valoración cambió desde que se generó la tesis.

data_freshness avisa cuando hay DATOS nuevos; esta señal avisa cuando cambia
el CÓDIGO del motor (MODEL_VERSION), que es cuando la ficha (recálculo en
vivo) y la tesis (snapshot de generación) pueden diverger sin dato nuevo.
Sin ruido del scheduler: compara versiones del motor, nunca timestamps.
"""
from app.services.thesis_service import ThesisService, engine_stale
from app.valuation.engines.base import MODEL_VERSION


def test_sin_version_persistida_devuelve_none_honesto():
    """Tesis anteriores a la señal: no se afirma ni vigente ni desactualizado."""
    assert engine_stale(None) is None
    assert engine_stale({}) is None
    assert engine_stale({"engine_version": None}) is None
    assert engine_stale({"engine_version": ""}) is None


def test_misma_version_no_marca():
    assert engine_stale({"engine_version": MODEL_VERSION}) is False


def test_version_distinta_marca():
    assert engine_stale({"engine_version": "valuation-engines-v1"}) is True
    assert engine_stale({"engine_version": "motor-viejo-cualquiera"}) is True


def test_valuation_basis_persiste_engine_version():
    """_valuation_basis liga la versión del motor del trace a la tesis."""
    valuation = {
        "value_per_share_basis": "10.0",
        "trace": {"model_version": MODEL_VERSION, "inferred_inputs": []},
    }
    basis = ThesisService._valuation_basis(valuation)
    assert basis is not None
    assert basis["engine_version"] == MODEL_VERSION


def test_valuation_basis_sin_model_version_omite_la_clave():
    """Sin version del motor en el trace la clave no existe: «desconocido»,
    distinto de None; engine_stale no afirma nada."""
    valuation = {"value_per_share_basis": "10.0", "trace": {}}
    basis = ThesisService._valuation_basis(valuation)
    assert basis is not None
    assert "engine_version" not in basis
    assert engine_stale(basis) is None


def test_engine_version_sola_no_crea_basis():
    """Contrato F394 vigente: una valoracion sin evidencia (sin base, inputs,
    convencion ni fecha de precio) no crea valuation_basis solo por la version
    del motor; esas tesis quedan con engine_stale=None (desconocido)."""
    valuation = {"trace": {"model_version": MODEL_VERSION}}
    assert ThesisService._valuation_basis(valuation) is None


def test_memo_avisa_cuando_el_motor_cambio():
    """El memo (y por tanto el audio, que locuta el memo) lleva el aviso."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.entities import Base, Company, ThesisVersion
    from app.services.thesis_memo import build_memo_markdown

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(
            ticker="PLTR", name="Palantir", exchange="NASDAQ", currency="USD",
            sector="Tech", industry="Software", company_type="growth",
            valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
        )
        db.add(company)
        db.flush()
        from app.models import FundamentalModelVersion

        db.add(FundamentalModelVersion(
            company_id=company.id, version=1, engine_version="test", algorithm_version="test",
            framework_key="dcf", horizon_years=10, status="ok", publishable=True,
            input_fingerprint="input", forecast_fingerprint="forecast",
            market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
        ))
        thesis = ThesisVersion(
            company_id=company.id, version=3, status="published", rating="watch",
            thesis_markdown="# t", executive_summary="Plataforma con traccion comercial.",
            valuation_basis={"engine_version": "valuation-engines-v1"},
        )
        db.add(thesis)
        db.flush()
        con_aviso = build_memo_markdown(db, company, thesis, engine_stale=True)
        sin_aviso = build_memo_markdown(db, company, thesis, engine_stale=False)
    assert "el motor de valoracion cambio" in con_aviso
    assert "motor de valoracion" not in sin_aviso
