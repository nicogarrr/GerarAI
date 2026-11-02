"""Aprobar o rechazar una lección del diario solo vale mientras está «proposed».

Una lección aprobada es inmutable (editarla da 409), pero «rechazar» la pasaba
a «rejected» sin más: desde una pestaña vieja, o pulsando dos veces, una lección
aprobada quedaba rechazada y su decisión seguía marcada «reviewed». Y aprobar
otra vez reescribía quién y cuándo la aprobó. La ficha solo ofrece los botones
para las lecciones propuestas; la API ahora hace lo mismo: repetir la misma
decisión no cambia nada y la contraria da 409."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, DecisionJournalEntry, DecisionLesson
from app.services.decision_learning_service import DecisionLearningService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _lesson(db, status="proposed"):
    company = Company(
        ticker="ACME", name="ACME", exchange="NASDAQ", currency="USD", sector="S", industry="I",
        company_type="holding", valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    entry = DecisionJournalEntry(
        company_id=company.id, decision_date=date(2026, 1, 5), decision="buy", rationale="Tesis",
        what_must_be_true=[], status="open", metadata_={},
    )
    db.add(entry)
    db.flush()
    lesson = DecisionLesson(
        decision_journal_entry_id=entry.id, company_id=company.id, taxonomy="other",
        cause="Causa", error="Error", lesson="Lección", future_application="Aplicación",
        evidence=[], status=status, metadata_={},
    )
    db.add(lesson)
    db.commit()
    return lesson, entry


def test_rechazar_una_leccion_aprobada_da_error_y_no_la_cambia(db):
    lesson, entry = _lesson(db)
    service = DecisionLearningService()
    service.decide(db, lesson, action="approve", actor="analyst")
    assert entry.status == "reviewed"
    with pytest.raises(ValueError, match="immutable"):
        service.decide(db, lesson, action="reject", actor="otra-pestana")
    db.refresh(lesson)
    assert lesson.status == "approved"
    assert "rejected_by" not in lesson.metadata_
    assert entry.status == "reviewed"


def test_aprobar_dos_veces_no_reescribe_quien_la_aprobo(db):
    lesson, _ = _lesson(db)
    service = DecisionLearningService()
    first = service.decide(db, lesson, action="approve", actor="analyst")
    approved_at = first.metadata_["approved_at"]
    again = service.decide(db, lesson, action="approve", actor="otra-persona")
    assert again.status == "approved"
    assert again.metadata_["approved_by"] == "analyst"
    assert again.metadata_["approved_at"] == approved_at


def test_aprobar_una_leccion_rechazada_pide_revisarla_antes(db):
    lesson, entry = _lesson(db, status="rejected")
    service = DecisionLearningService()
    with pytest.raises(ValueError, match="proposed"):
        service.decide(db, lesson, action="approve", actor="analyst")
    db.refresh(lesson)
    assert lesson.status == "rejected"
    assert entry.status == "open"
    # Rechazar otra vez no cambia nada.
    assert service.decide(db, lesson, action="reject", actor="analyst").status == "rejected"


def test_una_leccion_propuesta_se_aprueba_o_rechaza_como_siempre(db):
    lesson, entry = _lesson(db)
    rejected = DecisionLearningService().decide(db, lesson, action="reject", actor="analyst")
    assert rejected.status == "rejected"
    assert rejected.metadata_["rejected_by"] == "analyst"
    assert entry.status == "open"
