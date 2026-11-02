"""Revisiones: filtrar por un estado que no existe ya no devuelve 200 vacío.

GET /api/reviews?status=pendiente (o «Open») daba [] como si no hubiera nada
que revisar. Ahora da 400, igual que los filtros de alertas, sesiones y
afirmaciones. Los estados reales y la lista sin filtro siguen igual."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.reviews import list_reviews
from app.models.entities import Base, Company, ResearchReview


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        company = Company(
            ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
            sector="Tech", industry="Tech", company_type="holding",
            valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
        )
        session.add(company)
        session.flush()
        for status in ("open", "in_progress", "resolved"):
            session.add(ResearchReview(
                company_id=company.id, review_type="thesis_change", priority="high", title=f"Revisión {status}",
                summary=f"Revisión {status}", status=status,
            ))
        session.commit()
        yield session


@pytest.mark.parametrize("status", ["pendiente", "Open", "closed", "1e999"])
def test_estado_desconocido_es_400(db, status):
    with pytest.raises(HTTPException) as exc:
        list_reviews(ticker=None, status=status, limit=100, db=db)
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    ("status", "expected"),
    [("open", 1), ("in_progress", 1), ("resolved", 1), ("approved", 0), ("dismissed", 0), (None, 3), ("", 3)],
)
def test_estados_reales_y_sin_filtro_siguen_igual(db, status, expected):
    assert len(list_reviews(ticker=None, status=status, limit=100, db=db)) == expected
