"""Nota de tesis del vault Obsidian: la fecha es el día de Madrid de la última edición."""

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.obsidian import _load_thesis_notes
from app.models.entities import Base, Company, ThesisVersion


def _note_date(updated_at: datetime) -> str:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(
            ticker="OBSD", name="Obs", exchange="NYSE", currency="USD", sector="Tech",
            industry="Tech", company_type="standard", valuation_model="standard_dcf",
        )
        db.add(company)
        db.flush()
        db.add(ThesisVersion(
            company_id=company.id, version=1, status="final", thesis_markdown="# Tesis", executive_summary="Resumen.",
            rating="buy", updated_at=updated_at,
        ))
        db.commit()
        notes = _load_thesis_notes(db, company)
    engine.dispose()
    return notes[0].date


def test_late_utc_evening_is_next_madrid_day():
    # 23:30 UTC del 9 de marzo = 00:30 del 10 en Madrid.
    assert _note_date(datetime(2026, 3, 9, 23, 30)) == "2026-03-10"


def test_midday_unchanged():
    assert _note_date(datetime(2026, 3, 9, 12, 0)) == "2026-03-09"
