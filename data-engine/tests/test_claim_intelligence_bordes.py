"""Estados de revisión de claims con SQLite real, sin clasificador externo."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Claim,
    ClaimEvidence,
    EvidenceSuggestion,
    ResearchReview,
    Tenant,
    ThesisChange,
)
from app.services.claim_intelligence_service import ClaimIntelligenceService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(Tenant(id=1, external_id="claim-borders"))
            session.flush()
            session.info["tenant_id"] = 1
            yield session
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "relation,status,evidence",
    [
        ("uncertain", "uncertain", "uncertain"),
        ("contradicted", "contradicted", "contradicts"),
        ("superseded", "superseded", "supersedes"),
        ("stale", "stale", "context"),
    ],
)
def test_sugerencia_nueva_crea_claim_cambio_y_revision(db, relation, status, evidence):
    suggestion = EvidenceSuggestion(
        statement="Revenue grows 10 percent",
        relation=relation,
        confidence=0.9,
        rationale="new evidence",
        metadata_={"materiality_score": 8, "source_url": "source"},
    )
    db.add(suggestion)
    db.flush()
    service = ClaimIntelligenceService()
    claim = service.apply_suggestion(db, suggestion, automatic=True)
    db.flush()
    assert claim.status == status and claim.created_by == "automatic_extraction"
    assert claim.materiality_score == 8 and suggestion.suggested_claim_id == claim.id
    assert suggestion.status == "auto_applied" and claim.last_reviewed_at is not None
    assert db.scalar(select(ClaimEvidence)).evidence_type == evidence
    change = db.scalar(select(ThesisChange))
    assert change.requires_review is True and change.affected_claim_ids == [claim.id]
    assert db.scalar(select(ResearchReview)).claim_id == claim.id
    # Reaplicar al mismo claim no duplica la evidencia (no se afirma dedup de revisiones).
    service.apply_suggestion(db, suggestion, automatic=True)
    assert len(db.scalars(select(ClaimEvidence)).all()) == 1


def test_claim_supported_sin_procedencia_permanece_sin_verificar(db):
    suggestion = EvidenceSuggestion(statement="Revenue grows", relation="supported", confidence=0.9)
    db.add(suggestion)
    db.flush()
    claim = ClaimIntelligenceService().apply_suggestion(db, suggestion)
    assert claim.status == "unverified" and claim.created_by == "user_approved"
    assert suggestion.status == "pending"
    assert claim.last_reviewed_at is None


def test_scan_caducidad_crea_revision_una_vez(db):
    past = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    old = Claim(statement="expired", metadata_={"valid_until": past})
    already = Claim(statement="already stale", status="stale", metadata_={"valid_until": past})
    live = Claim(statement="no deadline", metadata_={})
    db.add_all([old, already, live])
    db.commit()
    service = ClaimIntelligenceService()
    assert service.scan_stale_claims(db) == {"scanned": 3, "stale": 1}
    assert old.status == "stale" and old.last_reviewed_at is not None
    assert live.status == "unverified"
    assert len(db.scalars(select(ResearchReview)).all()) == 1
    assert service.scan_stale_claims(db) == {"scanned": 3, "stale": 0}
    assert len(db.scalars(select(ResearchReview)).all()) == 1
