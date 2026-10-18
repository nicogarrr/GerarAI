"""Con flujo de caja operativo POSITIVO reportado, el rango indicativo sigue (contrato de #649)."""

import copy

import pytest
from fastapi.testclient import TestClient

import main
from app.core.database import init_db
from app.seed import seed
from tests import test_thesis_auto_ingest as base


@pytest.fixture(autouse=True)
def _cleanup_asts_evidence():
    yield
    base._clean_asts_evidence()


def test_positive_ocf_keeps_partial_indicative_range(monkeypatch):
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
    assert "parcial-indicativa" in thesis["executive_summary"]
    assert "RANGO INDICATIVO PARCIAL" in thesis["thesis_markdown"]
