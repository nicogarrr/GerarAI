"""Servicio de lectura SC 13D/13G: las limitaciones sobre plazos citan la
regla vigente con fuente primaria (eCFR), nunca un plazo inventado."""

from __future__ import annotations

from app.core.database import SessionLocal, init_db
from app.models.entities import Schedule13DGFiling
from app.services import schedule13dg_service


def _db():
    init_db()
    db = SessionLocal()
    db.query(Schedule13DGFiling).delete()
    db.commit()
    return db


def test_13g_deadline_limitation_matches_rule_with_primary_source():
    db = _db()
    result = schedule13dg_service.filings_for_ticker(db, "ZZT")
    text = " ".join(result["limitations"])
    # Rule 13d-1(b)(2): 45 dias tras el cierre del trimestre NATURAL, para
    # inversores institucionales cualificados (no "pasivos"; los pasivos son
    # 13d-1(c), 5 dias habiles). Fuente primaria: eCFR 17 CFR 240.13d-1.
    assert "13d-1(b)" in text
    assert "trimestre" in text
    assert "pasivo" not in text
    assert "ecfr.gov/current/title-17/chapter-II/part-240/section-240.13d-1" in text
    db.close()
