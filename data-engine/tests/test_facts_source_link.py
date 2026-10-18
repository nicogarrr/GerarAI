"""El endpoint /facts expone la procedencia enlazable de cada cifra.

Cada hecho con documento asociado devuelve la URL real del filing, el titulo
y la fecha de publicacion; un hecho sin documento devuelve nulos (el frontend
muestra la fuente como texto plano, nunca un enlace inventado).
"""
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import main
from app.core.database import SessionLocal, init_db
from app.models import Company, Document, FinancialFact
from app.seed import seed

DOC_URL = "https://www.sec.gov/Archives/edgar/data/789019/000095017025087843/msft-20250630.htm"
METRIC = "test_metric_source_link"
METRIC_HUELFRANA = "test_metric_sin_fuente"


def _cleanup() -> None:
    init_db()
    db = SessionLocal()
    try:
        for metric in (METRIC, METRIC_HUELFRANA):
            db.execute(delete(FinancialFact).where(FinancialFact.metric == metric))
        db.execute(delete(Document).where(Document.source_type == "sec_10k_test_source_link"))
        db.commit()
    finally:
        db.close()


def test_facts_exponen_enlace_y_fecha_de_la_fuente():
    _cleanup()
    init_db()
    seed()
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "MSFT"))
        assert company is not None
        doc = Document(
            company_id=company.id,
            title="MSFT 10-K FY2025",
            source_type="sec_10k_test_source_link",
            source_url=DOC_URL,
            published_at=datetime(2025, 7, 30, 12, 0, tzinfo=UTC),
        )
        db.add(doc)
        db.flush()
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=METRIC,
                value="281724000000",
                unit="USD",
                period="FY2025",
                fiscal_year=2025,
                source_id=doc.id,
                source_type="sec_test_source_link",
            )
        )
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=METRIC_HUELFRANA,
                value="42",
                unit="USD",
                period="FY2025",
                fiscal_year=2025,
                source_id=None,
                source_type="seed",
            )
        )
        db.commit()
    finally:
        db.close()

    try:
        client = TestClient(main.app)

        resp = client.get(f"/api/companies/MSFT/facts?metric={METRIC}")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["source_url"] == DOC_URL
        assert row["source_title"] == "MSFT 10-K FY2025"
        assert row["source_published_at"].startswith("2025-07-30")

        resp = client.get(f"/api/companies/MSFT/facts?metric={METRIC_HUELFRANA}")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["source_url"] is None
        assert row["source_title"] is None
        assert row["source_published_at"] is None
    finally:
        _cleanup()
