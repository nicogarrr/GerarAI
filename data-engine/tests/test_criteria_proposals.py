import pytest

from app.services.commitment_criteria_proposals import (
    PENDING_REVIEW,
    PROPOSALS,
    CriterionProposal,
    verify_quote_in_text,
)
from app.services.transcript_source_registry import is_official_transcript_url


def test_proposals_are_never_reviewed_or_consumable_and_source_is_registered():
    assert PROPOSALS
    for p in PROPOSALS:
        assert p.status == PENDING_REVIEW and p.consumable_by_engine is False
        assert is_official_transcript_url(p.ticker, p.source_url) and p.ambiguities


def test_cannot_forge_reviewed_status():
    p = PROPOSALS[0]
    with pytest.raises(ValueError):
        CriterionProposal(**{**p.__dict__, "status": "revisado"})
    with pytest.raises(ValueError):
        CriterionProposal(**{**p.__dict__, "consumable_by_engine": True})


def test_quote_verification_is_literal_single_and_page_checked():
    p = PROPOSALS[0]
    text = "\f".join(["a"] * 6 + [f"xx {p.quote} yy"])
    assert verify_quote_in_text(p, text)["ok"]
    assert verify_quote_in_text(p, "nada")["reason"] == "cita_ausente"
    assert verify_quote_in_text(p, f"{p.quote} {p.quote}")["reason"] == "cita_ambigua"
    assert verify_quote_in_text(p, f"{p.quote}")["reason"] == "pagina_distinta"


def test_engine_has_no_path_from_proposal():
    import app.services.management_credibility_service as svc
    from pathlib import Path
    assert "commitment_criteria_proposals" not in Path(svc.__file__).read_text()
