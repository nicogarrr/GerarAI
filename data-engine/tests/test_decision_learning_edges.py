"""Decision lesson editing boundaries use persisted ORM lessons."""

import pytest

from app.models import Company
from app.services.decision_learning_service import DecisionLearningService
from tests.test_leccion_decision_solo_propuesta import _lesson, db  # noqa: F401


@pytest.mark.parametrize(
    "metric,taxonomy",
    [
        ("SHARES_DILUTED", "underestimating_dilution"),
        ("dilution_rate", "underestimating_dilution"),
        ("operating_margin", "extrapolating_peak_margin"),
        ("net_debt", "ignoring_balance_sheet"),
        ("cash_balance", "ignoring_balance_sheet"),
        ("liquidity_ratio", "ignoring_balance_sheet"),
        ("market_size", "overestimating_TAM"),
        ("TAM", "overestimating_TAM"),
        ("revenue", "overestimating_TAM"),
        ("custom_metric", "thesis_drift"),
    ],
)
def test_taxonomy_mapping_is_case_insensitive_and_has_explicit_default(metric, taxonomy):
    assert DecisionLearningService._infer_taxonomy(metric) == taxonomy


def _edit(service, db, lesson, taxonomy="thesis_drift"):
    return service.update(
        db,
        lesson,
        taxonomy=taxonomy,
        cause="  cause  ",
        error="  error  ",
        lesson_text="  lesson  ",
        future_application="  next step  ",
    )


def test_approved_or_unsupported_edit_never_changes_persisted_lesson(db):
    lesson, _ = _lesson(db)
    service = DecisionLearningService()
    original = service.payload(lesson)
    with pytest.raises(ValueError, match="Unsupported decision error taxonomy"):
        _edit(service, db, lesson, taxonomy="made_up")
    db.refresh(lesson)
    assert service.payload(lesson) == original
    service.decide(db, lesson, action="approve", actor="analyst")
    approved = service.payload(lesson)
    with pytest.raises(ValueError, match="immutable"):
        _edit(service, db, lesson)
    db.refresh(lesson)
    assert service.payload(lesson) == approved


def test_edit_rejected_lesson_returns_to_proposed_and_payload_matches_storage(db):
    lesson, entry = _lesson(db, status="rejected")
    service = DecisionLearningService()
    edited = _edit(service, db, lesson)
    assert edited is lesson and lesson.status == "proposed"
    assert (lesson.cause, lesson.error, lesson.lesson, lesson.future_application) == (
        "cause",
        "error",
        "lesson",
        "next step",
    )
    assert entry.status == "open"
    company = db.get(Company, entry.company_id)
    rows = service.list(db, company)
    assert [item.id for item in rows] == [lesson.id]
    payload = service.payload(rows[0])
    assert payload["company_id"] == company.id and payload["decision_journal_entry_id"] == entry.id
    assert payload["taxonomy"] == "thesis_drift" and payload["status"] == "proposed"
    assert payload["cause"] == "cause" and payload["lesson"] == "lesson" and payload["evidence"] == []
    assert payload["metadata"] == lesson.metadata_
    assert payload["created_at"] == lesson.created_at and payload["updated_at"] == lesson.updated_at


def test_invalid_action_is_rejected_without_state_change(db):
    lesson, entry = _lesson(db)
    with pytest.raises(ValueError, match="approve or reject"):
        DecisionLearningService().decide(db, lesson, action="publish", actor="analyst")
    db.refresh(lesson)
    assert lesson.status == "proposed" and lesson.metadata_ == {}
    assert entry.status == "open"
