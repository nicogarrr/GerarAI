"""Con flujo de caja operativo POSITIVO reportado, el rango indicativo sigue (contrato de #649)."""

import copy

import pytest
from fastapi.testclient import TestClient

import main
from app.core.database import init_db
from app.seed import seed
from tests import test_thesis_auto_ingest as base


@pytest.fixture(autouse=True)
def _private_database(tmp_path, monkeypatch):
    """BD SQLite propia para este test (antes compartía la BD de la sesión y
    fallaba de forma intermitente según lo que otros tests dejaban de ASTS:
    tesis previas, supuestos, splits...). SessionLocal se re-enlaza en sitio
    (configure) porque muchos módulos lo importan por nombre."""
    from sqlalchemy import create_engine

    from app.core import database

    private = create_engine(
        f"sqlite:///{(tmp_path / 'positive_cash.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    previous_bind = database.SessionLocal.kw.get("bind")
    monkeypatch.setattr(database, "engine", private)
    database.SessionLocal.configure(bind=private)
    try:
        yield
    finally:
        database.SessionLocal.configure(bind=previous_bind)
        private.dispose()


def test_positive_ocf_keeps_partial_indicative_range(monkeypatch):
    from app.core import database

    with database.SessionLocal() as probe:
        assert "positive_cash.db" in str(probe.get_bind().url)
    init_db()
    seed()
    base._clean_asts_evidence()
    facts = copy.deepcopy(base.FAKE_COMPANYFACTS)
    ocf = facts["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]
    ocf["units"]["USD"] = [base._xbrl(20_000_000, "2024-12-31", "2025-02-28")]
    base._mock_all_sources(monkeypatch)
    monkeypatch.setattr(
        base.ThesisEvidenceService, "_fetch_company_facts", lambda self, cik: facts
    )
    base._seed_evidence_rows()
    client = TestClient(main.app)

    response = client.post("/api/thesis/generate", json={"ticker": "ASTS", "force_new_version": True})
    assert response.status_code == 200
    thesis = response.json()
    assert thesis["status"] == "draft"
    assert thesis["base_value"] is not None
    # B6: la etiqueta de indicativa viaja en la hipotesis; la cifra NO se oculta.
    assert "Valoración indicativa sobre supuestos" in thesis["executive_summary"]
    # Margen estándar (V - P)/V: con V muy por debajo de P sale muy negativo
    # (antes, con V/P - 1, era -97,9 %; ambos describen V ~ 2,1 % de P).
    assert "margen de seguridad del -4725,6 %" in thesis["executive_summary"]
    assert "RANGO INDICATIVO PARCIAL" in thesis["thesis_markdown"]
