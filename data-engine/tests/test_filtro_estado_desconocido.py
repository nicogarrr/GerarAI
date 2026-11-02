"""Listas con filtro de estado: un estado que no existe ya no da 200 vacío.

GET /api/alerts?status=bogus y GET /api/research-sessions?status=bogus
devolvían 200 [] (un error de tecleo parecía «no hay nada»). Ahora la
API lo dice: 422 en alertas y 400 en sesiones (igual que el filtro de
ámbito de /api/memory-items). Los estados reales siguen filtrando igual.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.alerts import list_alerts
from app.api.routes.memory import list_research_sessions
from app.models.entities import Base, Company, ResearchAlert, ResearchSession


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
        for status in ("open", "acknowledged", "resolved"):
            session.add(ResearchAlert(
                company_id=company.id, alert_type="price_above", severity="high",
                title=f"AAPL {status}", message="m", fingerprint=f"fp-{status}",
                channels=["in_app"], status=status,
            ))
        for status in ("open", "closed"):
            session.add(ResearchSession(
                company_id=company.id, title=f"Sesión {status}", question="¿Por qué?", status=status,
            ))
        session.commit()
        yield session


@pytest.mark.parametrize("status", ["bogus", "OPEN", "abierta", "open "])
def test_alertas_estado_desconocido_es_422(db, status):
    with pytest.raises(HTTPException) as exc:
        list_alerts(ticker=None, status=status, include_snoozed=False, limit=100, db=db)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("status", ["open", "acknowledged", "resolved", "snoozed"])
def test_alertas_estados_reales_siguen_filtrando(db, status):
    result = list_alerts(ticker=None, status=status, include_snoozed=False, limit=100, db=db)
    assert all(a.status == status for a in result)
    if status != "snoozed":
        assert [a.title for a in result] == [f"AAPL {status}"]


def test_alertas_sin_filtro_igual_que_antes(db):
    result = list_alerts(ticker=None, status=None, include_snoozed=False, limit=100, db=db)
    assert len(result) == 3


@pytest.mark.parametrize("status", ["bogus", "OPEN", "cerrada"])
def test_sesiones_estado_desconocido_es_400(db, status):
    with pytest.raises(HTTPException) as exc:
        list_research_sessions(ticker=None, status=status, limit=50, db=db)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("status", ["open", "closed", "active", "archived"])
def test_sesiones_estados_reales_siguen_filtrando(db, status):
    result = list_research_sessions(ticker=None, status=status, limit=50, db=db)
    assert all(s.status == status for s in result)
    assert len(result) == (1 if status in ("open", "closed") else 0)
