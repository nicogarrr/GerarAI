"""RedTeamService contract tests.

The red team is the deterministic bear-case attack on a thesis: findings
must come only from stored evidence state, the score must follow the
severity penalties exactly, and an empty attack must say so honestly
instead of claiming low risk.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Claim,
    Company,
    RedTeamRun,
    ResearchReview,
    SourceAudit,
    ThesisVersion,
)
from app.services.red_team_service import SEVERITY_PENALTY, RedTeamService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _claim(db: Session, company: Company, **kwargs) -> Claim:
    claim = Claim(
        company_id=company.id,
        statement=kwargs.pop("statement", "A material claim"),
        confidence=Decimal("0.6"),
        **kwargs,
    )
    db.add(claim)
    db.commit()
    return claim


def test_run_flags_unsupported_material_and_unfalsifiable_claims(db):
    company = _company(db)
    _claim(
        db, company,
        statement="Moat keeps expanding",
        materiality_score=8,  # >=7, no evidence rows, no invalidation conditions
    )
    run = RedTeamService().run(db, company)

    assert run.status == "completed"
    types = {finding["type"] for finding in run.findings}
    assert "unsupported_material_claim" in types
    # Un claim, un hallazgo: los motivos se fusionan en un solo finding con
    # el statement una sola vez (el rastro conserva todos los tipos).
    assert "missing_falsification_test" not in types
    merged = [
        finding
        for finding in run.findings
        if finding["type"] == "unsupported_material_claim"
    ]
    assert merged
    assert merged[0]["trace"].get("merged_types") == [
        "unsupported_material_claim",
        "missing_falsification_test",
    ]
    assert merged[0]["message"].count("Moat keeps expanding") == 1
    assert "sin evidencia vinculada" in merged[0]["message"]
    assert "invalidación" in merged[0]["message"]
    # Empty valuation is never publishable: the attack must say so.
    assert "valuation_not_publishable" in types

    expected = max(0, 100 - sum(SEVERITY_PENALTY[f["severity"]] for f in run.findings))
    assert run.score == expected
    # Unsupported material claims land under missing_risks, not broken assumptions.
    assert any("Moat keeps expanding" in item for item in run.missing_risks)
    # No invalidation conditions anywhere: honest fallback test instruction.
    assert run.falsification_tests == [
"Define condiciones de invalidación explícitas y medibles para cada afirmación material de la tesis."
    ]
    # Findings trigger an open red-team review for the user.
    review = db.scalar(
        select(ResearchReview).where(
            ResearchReview.company_id == company.id,
            ResearchReview.review_type == "red_team",
        )
    )
    assert review is not None


def test_merged_claim_keeps_all_types_in_category_lists(db):
    """Un claim contradicho+sin evidencia fusiona en un hallazgo, pero los
    motivos fusionados no desaparecen de broken_assumptions ni de
    missing_risks (regresión señalada en revisión)."""
    company = _company(db)
    _claim(
        db, company,
        statement="Revenue doubles every year",
        status="contradicted", materiality_score=9,  # sin evidencia ni invalidación
    )
    run = RedTeamService().run(db, company)

    merged = [
        finding
        for finding in run.findings
        if "Revenue doubles every year" in finding["message"]
    ]
    assert len(merged) == 1, run.findings
    finding = merged[0]
    assert finding["type"] == "claim_contradicted"  # critical domina
    assert finding["trace"].get("merged_types") == [
        "unsupported_material_claim",
        "claim_contradicted",
        "missing_falsification_test",
    ]
    # Antes de la fusión había dos findings y el claim entraba en ambas
    # listas; los derivados por categoría deben mirar los tipos fusionados:
    # el motivo unsupported sigue contando como riesgo ausente aunque el
    # tipo dominante del hallazgo sea claim_contradicted.
    assert any("Revenue doubles every year" in item for item in run.broken_assumptions)
    assert any("Revenue doubles every year" in item for item in run.missing_risks)


def test_run_marks_contradicted_claims_as_broken_assumptions(db):
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="draft",
        thesis_markdown="# t", executive_summary="e",
    )
    db.add(thesis)
    _claim(
        db, company,
        statement="Revenue grows 20 percent",
        status="contradicted", materiality_score=9,
        metadata_={"invalidation_conditions": ["Growth below 5 percent for two quarters"]},
    )
    run = RedTeamService().run(db, company)

    crit = [f for f in run.findings if f["type"] == "claim_contradicted"]
    assert crit and crit[0]["severity"] == "critical"  # contradicted + materiality >= 8
    assert any("Revenue grows 20 percent" in item for item in run.broken_assumptions)
    assert run.falsification_tests == ["Growth below 5 percent for two quarters"]
    # The thesis row carries the red-team score.
    assert thesis.red_team_score == run.score


def test_run_without_findings_is_honest_about_coverage(db):
    company = _company(db)
    # No claims, no thesis: the only finding is the unpublished valuation.
    run = RedTeamService().run(db, company)

    assert run.status == "completed"
    assert run.trace["method"] == "deterministic_evidence_attack_v1"
    assert run.trace["claim_count"] == 0
    if not run.findings:
        assert "cobertura insuficiente" in run.strongest_bear_case
    else:
        # With no claims the valuation finding dominates the attack.
        assert run.findings[0]["type"] == "valuation_not_publishable"


def test_run_flags_blocked_audit_with_backing_score_not_coverage(db):
    # F301: una auditoría NO superada con afirmaciones limpias (puntuación 100,
    # sin sin-respaldo) es un bloqueo aguas abajo. El mensaje debe hablar de
    # «puntuación de respaldo de afirmaciones», nunca de «cobertura» (la
    # puntuación no es cobertura global) y debe admitir otras causas de bloqueo.
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="draft",
        thesis_markdown="# t", executive_summary="e",
    )
    db.add(thesis)
    db.flush()
    db.add(
        SourceAudit(
            thesis_version_id=thesis.id,
            passed=False,
            source_coverage_score=100,
            unsupported_claims=[],
            data_conflicts=[],
            required_fixes=["trace_missing"],
        )
    )
    db.commit()

    run = RedTeamService().run(db, company)

    blocked = [f for f in run.findings if f["type"] == "source_audit_blocked"]
    assert blocked, run.findings
    message = blocked[0]["message"]
    assert "puntuación de respaldo de afirmaciones 100/100" in message
    assert "cobertura" not in message
    assert "traza" in message


def test_run_does_not_duplicate_open_review(db):
    company = _company(db)
    _claim(db, company, materiality_score=8)
    service = RedTeamService()
    service.run(db, company)
    service.run(db, company)

    assert db.scalar(
        select(ResearchReview).where(
            ResearchReview.company_id == company.id,
            ResearchReview.review_type == "red_team",
        )
    ) is not None
    reviews = db.scalars(
        select(ResearchReview).where(
            ResearchReview.company_id == company.id,
            ResearchReview.review_type == "red_team",
        )
    ).all()
    assert len(reviews) == 1
    assert db.scalars(select(RedTeamRun).where(RedTeamRun.company_id == company.id)).all().__len__() == 2


def test_valuation_not_publishable_message_names_missing_inputs_in_spanish():
    from app.services.red_team_service import _valuation_not_publishable_message

    msg = _valuation_not_publishable_message(
        ["fiscal_year", "book_value_growth", "free cash flow or fcf margin", "combined_ratio"]
    )
    assert "año fiscal" in msg and "crecimiento del valor contable" in msg
    assert "flujo de caja libre o margen FCF" in msg and "ratio combinado" in msg
    assert "fiscal_year" not in msg and "book_value_growth" not in msg
    # Clave desconocida: espacios, nunca el identificador crudo con guiones bajos.
    assert "dato raro" in _valuation_not_publishable_message(["dato_raro"])
    assert "necesarios" in _valuation_not_publishable_message([])
