"""Lista 13.1: GET /peers/comparison es solo lectura; persistir va por POST.

Antes, GET ...?refresh=true recalculaba y PERSISTIA CalculatedMetrics
(persist=refresh): un GET mutante. Ahora el GET siempre llama con
refresh=False y el recalculo persistente vive en
POST /peers/comparison/refresh.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import companies as companies_routes
from app.models.entities import Base, Company


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = 1
        yield session


@pytest.fixture
def company(db):
    row = Company(
        ticker="TSTGET", name="TSTGET", exchange="NASDAQ", currency="USD",
        sector="Technology", industry="Software", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def _fake_compare(self, db, company, limit=8, metrics=None, refresh=False):
        calls.append({"limit": limit, "metrics": metrics, "refresh": refresh})
        return {"ticker": company.ticker, "refresh": refresh}

    monkeypatch.setattr(companies_routes.PeerComparisonService, "compare", _fake_compare)
    return calls


def test_get_never_persists_even_with_refresh_param_gone(db, company, captured):
    result = companies_routes.peer_comparison("TSTGET", limit=8, metrics=None, db=db)
    assert len(captured) == 1
    assert captured[0]["refresh"] is False
    assert result["refresh"] is False


def test_post_refresh_persists(db, company, captured):
    result = companies_routes.refresh_peer_comparison("TSTGET", limit=8, metrics=None, db=db)
    assert len(captured) == 1
    assert captured[0]["refresh"] is True
    assert result["refresh"] is True


def test_get_signature_has_no_refresh_query_param():
    import inspect

    params = inspect.signature(companies_routes.peer_comparison).parameters
    assert "refresh" not in params, "un GET no puede exponer un parametro que muta"
