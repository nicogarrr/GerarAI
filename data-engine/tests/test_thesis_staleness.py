"""Senal de frescura: /api/thesis/{ticker}/latest marca stale=true cuando hay
datos de la empresa (hechos, precios, noticias, documentos) posteriores a la
version de la tesis.

Run from data-engine/:
    pytest tests/test_thesis_staleness.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core.database import SessionLocal, init_db
from app.models import Company, Document, FinancialFact, MarketPrice, NewsEvent, ThesisVersion
from app.seed import seed

TICKER = "ASTS"


def _clean() -> None:
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == TICKER))
        if company:
            # Freshness checks all four inputs, not only financial facts.
            # Earlier suites can leave ASTS prices/news/documents behind.
            for model in (FinancialFact, MarketPrice, NewsEvent, Document):
                db.query(model).filter(model.company_id == company.id).delete()
            db.query(ThesisVersion).filter(ThesisVersion.company_id == company.id).delete()
            db.commit()
    finally:
        db.close()


def _make_thesis() -> int:
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == TICKER))
        assert company is not None
        # created_at/updated_at antiguos para controlar la comparacion
        old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
        thesis = ThesisVersion(
            company_id=company.id,
            version=99,
            status="draft",
            thesis_markdown="# tesis de prueba",
            executive_summary="resumen de prueba",
            rating="watch",
            data_confidence_score=0,
            source_coverage_score=0,
            red_team_score=0,
            valuation_risk_score=0,
            created_at=old,
            updated_at=old,
        )
        db.add(thesis)
        db.commit()
        return company.id
    finally:
        db.close()


def test_latest_not_stale_without_newer_data() -> None:
    init_db()
    seed()
    _clean()
    _make_thesis()

    client = TestClient(main.app)
    response = client.get(f"/api/thesis/{TICKER}/latest")
    assert response.status_code == 200
    payload = response.json()
    assert payload["stale"] is False


def test_latest_stale_when_newer_facts_exist() -> None:
    init_db()
    seed()
    _clean()
    company_id = _make_thesis()

    db = SessionLocal()
    try:
        db.add(
            FinancialFact(
                company_id=company_id,
                metric="revenue",
                value=Decimal("1000000"),
                unit="USD",
                period="FY2025",
                fiscal_year=2025,
                source_type="seed",
            )
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(main.app)
    response = client.get(f"/api/thesis/{TICKER}/latest")
    assert response.status_code == 200
    payload = response.json()
    assert payload["stale"] is True
    assert payload["latest_data_at"] is not None
