"""La misma cifra de una tesis no puede divergir entre vistas.

Ficha de tesis (GET /thesis/{ticker}) y snapshot de empresa (que alimenta la
carta y la ficha) deben mostrar el mismo rating y las mismas cifras, o ambos
retenerlas. Datos sinteticos fijos; la comparacion es directa.
"""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.thesis import latest_thesis
from app.models.entities import Base, Company, FundamentalModelVersion, Tenant, ThesisVersion
from app.services.company_snapshot_service import CompanySnapshotService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        tenant = Tenant(external_id="cons", name="Cons", status="active", metadata_={})
        company = Company(ticker="CONS", name="Cons Co", exchange="NASDAQ", currency="USD",
                          company_type="mature", valuation_model="dcf")
        db_t = tenant
        session.add_all([db_t, company])
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session, company
    engine.dispose()


def _thesis(session, company, **overrides):
    thesis = ThesisVersion(
        tenant_id=session.info["tenant_id"], company_id=company.id, version=1,
        status="published", rating="buy", executive_summary="Tesis de prueba",
        thesis_markdown="# tesis", current_price=Decimal("50"),
        bear_value=Decimal("80"), base_value=Decimal("100"), bull_value=Decimal("130"),
        expected_value=Decimal("104"), margin_of_safety=Decimal("0.50"),
        data_confidence_score=80, source_coverage_score=90, red_team_score=70,
        valuation_risk_score=20,
        valuation_basis={"margin_of_safety_convention": "discount_to_value_v1"},
        created_at=datetime(2026, 10, 1, tzinfo=UTC))
    for key, value in overrides.items():
        setattr(thesis, key, value)
    session.add(thesis)
    session.commit()
    return thesis


def _model(session, company, *, publishable):
    model = FundamentalModelVersion(
        tenant_id=session.info["tenant_id"], company_id=company.id, version=1,
        engine_version="test", algorithm_version="test", framework_key="dcf",
        horizon_years=10, status="ok", publishable=publishable,
        input_fingerprint="input-1", forecast_fingerprint="f",
        market_snapshot_fingerprint="m", valuation_snapshot_fingerprint="v")
    session.add(model)
    session.commit()
    return model


def _get(payload, key):
    if isinstance(payload, dict):
        return payload[key]
    return getattr(payload, key)


def _figures(payload):
    return {key: _get(payload, key) for key in ("rating", "margin_of_safety", "expected_value",
                                                "bear_value", "base_value", "bull_value")}


def test_same_figures_when_model_publishable(db):
    session, company = db
    _thesis(session, company)
    _model(session, company, publishable=True)

    route = latest_thesis(company.ticker, session)
    snapshot = CompanySnapshotService().build(session, company)

    assert _figures(route) == _figures(snapshot.latest_thesis)
    assert _get(snapshot.valuation_summary, "margin_of_safety") == route["margin_of_safety"]
    assert _get(snapshot.valuation_summary, "expected_value") == route["expected_value"]
    assert route["rating"] == "buy"


def test_both_withhold_when_no_publishable_model(db):
    session, company = db
    _thesis(session, company)
    _model(session, company, publishable=False)

    route = latest_thesis(company.ticker, session)
    snapshot = CompanySnapshotService().build(session, company)

    assert _figures(route) == _figures(snapshot.latest_thesis)
    assert route["rating"] == "insufficient_data"
    assert route["margin_of_safety"] is None
    assert route["margin_of_safety_status"] == "withheld"
    assert _get(snapshot.valuation_summary, "margin_of_safety") is None
    assert _get(snapshot.valuation_summary, "margin_of_safety_status") == "withheld"
