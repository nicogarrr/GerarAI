"""Refuerzo de clasificación y creación de sugerencias sin veredicto externo real."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Claim, Company, Document, DocumentChunk, EvidenceSuggestion, Tenant
from app.services import claim_intelligence_service as svc
from app.services import jev_gates


@pytest.mark.parametrize(
    "label,confidence,expected",
    [
        ("contradicted", 0.85, "contradicted"),
        ("superseded", 0.99, "superseded"),
        ("stale", 0.9, "stale"),
        ("supported", 1.0, "uncertain"),
        ("contradicted", 0.84, "uncertain"),
        ("contradicted", float("nan"), "uncertain"),
        ("contradicted", float("inf"), "uncertain"),
        ("contradicted", -1, "uncertain"),
        ("contradicted", 1.01, "uncertain"),
        ("unknown", 1, "uncertain"),
    ],
)
def test_veredicto_solo_adopta_duda_fuerte(monkeypatch, label, confidence, expected):
    calls = []

    def verdict(claim, candidate):
        calls.append((claim, candidate))
        return SimpleNamespace(label=label, confidence=confidence)

    monkeypatch.setattr(jev_gates, "jev_claim_relation_sync", verdict)
    claim = Claim(statement="Satellite capacity expands", metadata_={"valid_until": "bad-date"})
    out = svc.ClaimIntelligenceService().classify_relation(
        claim=claim,
        candidate="Factory output grows",
        similarity=0.2,
        evidence_date=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert out.relation == expected
    if expected != "uncertain":
        assert out.confidence == confidence and "Jev claim_relation" in out.rationale
    assert calls == [("Satellite capacity expands", "Factory output grows")]


def test_veredicto_fallido_no_rompe_y_optout_no_consulta(monkeypatch):
    calls = []

    def broken(*args):
        calls.append(args)
        raise RuntimeError("offline")

    monkeypatch.setattr(jev_gates, "jev_claim_relation_sync", broken)
    claim = Claim(statement="Capacity expands", metadata_={})
    service = svc.ClaimIntelligenceService()
    for use in (True, False):
        assert (
            service.classify_relation(
                claim=claim, candidate="Other report", similarity=0.2, use_jev=use
            ).relation
            == "uncertain"
        )
    assert len(calls) == 1


def test_documento_sin_match_crea_sugerencia_pendiente_y_deduplica(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(jev_gates, "mark_only", lambda *args, **kwargs: {"label": "verifiable"})
    try:
        with Session(engine) as db:
            db.add(Tenant(id=1, external_id="claim-classification"))
            db.flush()
            db.info["tenant_id"] = 1
            company = Company(
                ticker="CLAIMTEST",
                name="Test",
                exchange="TEST",
                currency="USD",
                company_type="operating",
                valuation_model="unassigned",
            )
            db.add(company)
            db.flush()
            doc = Document(
                company_id=company.id,
                title="Test",
                source_type="SEC",
                source_url="https://example.test/filing",
            )
            db.add(doc)
            db.flush()
            db.add(DocumentChunk(document_id=doc.id, chunk_index=0, text="material report", token_count=2))
            db.commit()
            service = svc.ClaimIntelligenceService()
            monkeypatch.setattr(
                service,
                "extract_statements",
                lambda text: [svc.ExtractedStatement("Revenue forecast $100 million", 0.9, 8, "quote")],
            )
            out = service.scan_document(db, doc)
            assert out["suggestions"] == 1 and out["applied"] == 0
            row = db.scalar(select(EvidenceSuggestion))
            assert row.status == "pending" and row.suggested_claim_id is None
            assert row.relation == "uncertain" and row.suggestion_type == "create_claim"
            assert row.metadata_["jev_claim_routing"] == {"label": "verifiable"}
            assert service.scan_document(db, doc)["suggestions"] == 0
            assert len(db.scalars(select(EvidenceSuggestion)).all()) == 1
    finally:
        engine.dispose()


@pytest.fixture
def text_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(Tenant(id=1, external_id="text-classification"))
            db.flush()
            db.info["tenant_id"] = 1
            company = Company(
                ticker="TEXTTEST",
                name="Test",
                exchange="TEST",
                currency="USD",
                company_type="operating",
                valuation_model="unassigned",
            )
            db.add(company)
            db.commit()
            yield db, company
    finally:
        engine.dispose()


def test_scan_text_sin_match_conserva_procedencia_y_fallback(text_db, monkeypatch):
    db, company = text_db
    service = svc.ClaimIntelligenceService()
    monkeypatch.setattr(service, "extract_statements", lambda text: [])
    text = "  Revenue   expected to reach 100 million next year  "
    out = service.scan_text(
        db,
        company=company,
        text=text,
        source_type="SEC",
        source_url="https://example.test/source",
        source_reference={"filing": "id"},
    )
    assert out["suggestions"] == 1 and out["applied"] == 0 and out["relations"] == {"uncertain": 1}
    row = db.scalar(select(EvidenceSuggestion))
    assert row.statement == "Revenue expected to reach 100 million next year"
    assert row.suggested_claim_id is None and row.status == "pending"
    assert row.metadata_["source_reference"] == {"filing": "id"}
    assert row.metadata_["source_url"] == "https://example.test/source"
    assert row.metadata_["confidence_source"] == "heuristic"
    assert service.scan_text(db, company=company, text="short", source_type="SEC") == {
        "suggestion_ids": [],
        "suggestions": 0,
        "applied": 0,
        "relations": {},
    }


@pytest.mark.parametrize("auto_apply", [True, False])
def test_scan_text_match_contradicho_y_revision(text_db, monkeypatch, auto_apply):
    db, company = text_db
    claim = Claim(company_id=company.id, statement="Revenue expected 100 million", status="unverified")
    db.add(claim)
    db.commit()
    service = svc.ClaimIntelligenceService()
    monkeypatch.setattr(
        service,
        "extract_statements",
        lambda text: [
            svc.ExtractedStatement("Revenue expected 80 million", 0.9, 8, "Revenue expected 80 million")
        ],
    )
    out = service.scan_text(
        db, company=company, text="local evidence", source_type="SEC", auto_apply=auto_apply
    )
    assert out["suggestions"] == 1 and out["relations"] == {"contradicted": 1}
    assert out["applied"] == int(auto_apply)
    row = db.scalar(select(EvidenceSuggestion))
    assert row.suggested_claim_id == claim.id and row.metadata_["confidence_source"] == "extraction_rules"
    assert row.status == ("auto_applied" if auto_apply else "pending")
    assert claim.status == ("contradicted" if auto_apply else "unverified")
