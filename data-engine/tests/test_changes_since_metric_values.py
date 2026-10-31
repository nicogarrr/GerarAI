"""«Qué ha cambiado» (idea Jera Value): valor anterior → nuevo por métrica en changes-since,
derivado de los hechos ya guardados (sin migraciones)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact
from app.services.company_changes_service import changes_since

SINCE = datetime(2026, 10, 1, tzinfo=UTC)


def _fact(db, company, metric, value, period, when, source="sec_xbrl"):
    db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(value), unit="USD", period=period,
                         source_type=source, created_at=when, updated_at=when))


def test_changes_since_lists_old_and_new_value_per_metric():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(ticker="CHG", name="Change Co", exchange="NASDAQ", currency="USD", sector="T", industry="T",
                          company_type="stock", valuation_model="dcf", special_sources=[], special_risks=[], factor_tags=[])
        db.add(company)
        db.flush()
        before, after = datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 15, tzinfo=UTC)
        _fact(db, company, "revenue", "100", "FY2025", before)
        _fact(db, company, "revenue", "104", "FY2025", after)  # revisión del mismo periodo
        _fact(db, company, "fcf", "20", "Q2 2026", before)
        _fact(db, company, "fcf", "26", "Q3 2026", after)  # periodo nuevo
        _fact(db, company, "eps", "1.5", "Q3 2026", after)  # sin dato previo
        db.commit()
        out = changes_since(db, company.id, SINCE)
    by_metric = {c["metric"]: c for c in out["cambios_metricas"]}
    assert by_metric["revenue"]["anterior"]["valor"] == 100.0 and by_metric["revenue"]["nuevo"]["valor"] == 104.0
    assert by_metric["fcf"]["anterior"]["periodo"] == "Q2 2026" and by_metric["fcf"]["nuevo"]["periodo"] == "Q3 2026"
    assert by_metric["eps"]["anterior"] is None
    assert all(c["fuente"] == "sec_xbrl" for c in out["cambios_metricas"])
