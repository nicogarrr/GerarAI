"""Actor scan_contradictions: lee solo las columnas que usa de claim_evidence
y thesis_changes.

Antes cargaba filas ORM completas de ambas tablas (con summary/quote en Text)
para usar solo claim_id y affected_claim_ids. La proyeccion lee solo esas
columnas; el comportamiento (claims marcados, cambios creados, ya flagueados)
es identico.

Run from data-engine/:
    pytest tests/test_worker_scan_contradictions_projection.py -v
"""

import re
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Claim, ClaimEvidence, Company, Tenant, ThesisChange
from app.services.thesis_change_types import claim_change_type
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="sc", name="t", metadata_={})
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    company = Company(ticker="AAA", name="AAA", exchange="NYSE", currency="USD", company_type="generic",
                      valuation_model="dcf", special_sources=[], special_risks=[], factor_tags=[])
    db.add(company)
    db.flush()
    # claim1: evidencia contradictoria y YA flagueado -> no duplica cambio.
    # claim2: evidencia contradictoria sin flaguear -> crea cambio.
    claim1 = Claim(company_id=company.id, statement="crece un 20%", status="unverified", materiality_score=6)
    claim2 = Claim(company_id=company.id, statement="margen alto", status="unverified", materiality_score=4)
    db.add_all([claim1, claim2])
    db.flush()
    db.add_all([
        ClaimEvidence(claim_id=claim1.id, evidence_type="contradicts", summary="contra", quote="q" * 500),
        ClaimEvidence(claim_id=claim1.id, evidence_type="contradicts", summary="contra2"),
        ClaimEvidence(claim_id=claim2.id, evidence_type="contradicts", summary="contra3"),
        ClaimEvidence(claim_id=claim2.id, evidence_type="supports", summary="apoya"),
    ])
    db.add(ThesisChange(company_id=company.id, change_type=claim_change_type("contradicted"),
                        summary="ya flagueado", affected_claim_ids=[claim1.id], requires_review=True))
    db.commit()
    statements: list[str] = []

    def _capture(conn, cur, stmt, params, ctx, many):
        statements.append(stmt)

    event.listen(engine, "before_cursor_execute", _capture)
    monkeypatch.setattr(worker, "_session", lambda tenant_id, user_id: db)
    monkeypatch.setattr(db, "close", lambda: None)
    return SimpleNamespace(db=db, claim1=claim1, claim2=claim2, statements=statements)


def _selects_against(statements, table):
    return [s for s in statements if s.lstrip().upper().startswith("SELECT") and f"FROM {table.upper()}" in s.upper()]


def test_comportamiento_identico(env):
    out = worker.scan_contradictions.fn(tenant_id=1, user_id="u")
    assert out == {
        "status": "ok",
        "actor": "scan_contradictions",
        "contradictory_evidence": 3,
        "claims_flagged": 2,
        "changes_created": 1,
    }
    env.db.expire_all()
    assert env.claim1.status == "contradicted"
    assert env.claim2.status == "contradicted"
    changes = env.db.query(ThesisChange).all()
    assert len(changes) == 2
    nuevo = [c for c in changes if c.affected_claim_ids == [env.claim2.id]]
    assert len(nuevo) == 1
    assert nuevo[0].change_type == claim_change_type("contradicted")


def test_claim_evidence_se_lee_proyectada(env):
    worker.scan_contradictions.fn(tenant_id=1, user_id="u")
    selects = _selects_against(env.statements, "claim_evidence")
    assert selects, "se esperaba al menos una lectura de claim_evidence"
    for stmt in selects:
        assert re.search(r"claim_evidence\.claim_id", stmt), stmt
        assert "claim_evidence.summary" not in stmt, stmt
        assert "claim_evidence.quote" not in stmt, stmt


def test_thesis_changes_se_lee_proyectada(env):
    worker.scan_contradictions.fn(tenant_id=1, user_id="u")
    selects = _selects_against(env.statements, "thesis_changes")
    assert selects, "se esperaba al menos una lectura de thesis_changes"
    for stmt in selects:
        assert re.search(r"thesis_changes\.affected_claim_ids", stmt), stmt
        assert "thesis_changes.summary" not in stmt, stmt
