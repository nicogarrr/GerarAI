"""Home and watchlist must not treat archived thesis values as current fair value."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes import valuation, watchlist
from app.models.entities import Base, Company, FundamentalModelVersion, Tenant, ThesisVersion
from app.services import fair_value_service as fvs


@pytest.fixture
def saved():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        tenant = Tenant(external_id="gate", name="Gate", status="active", metadata_={})
        other = Tenant(external_id="other", name="Other", status="active", metadata_={})
        company = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD", company_type="mature", valuation_model="dcf")
        db.add_all([tenant, other, company])
        db.flush()
        db.info["tenant_id"] = tenant.id
        thesis = ThesisVersion(tenant_id=tenant.id, company_id=company.id, version=3,
            status="published", rating="buy", executive_summary="ARCHIVED_PROSE margen -65,1% valor 119,92",
            thesis_markdown="ARCHIVED_MEMO", expected_value=Decimal("119.92"),
            margin_of_safety=Decimal("-0.651"), valuation_risk_score=87,
            created_at=datetime(2026, 10, 1, tzinfo=UTC))
        db.add(thesis)
        db.commit()
        yield db, company, thesis, other
    engine.dispose()


def model(db, company, *, publishable, version=1, tenant_id=None):
    row = FundamentalModelVersion(tenant_id=tenant_id or db.info["tenant_id"],
        company_id=company.id, version=version, engine_version="test", algorithm_version="test",
        framework_key="dcf", horizon_years=10, status="ok", publishable=publishable,
        input_fingerprint=f"input-{version}", forecast_fingerprint="forecast",
        market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation")
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("publishable", [False, None])
def test_home_batch_and_watchlist_never_expose_blocked_thesis(saved, monkeypatch, publishable):
    import asyncio

    db, company, thesis, _ = saved
    if publishable is not None:
        model(db, company, publishable=publishable)
    async def earnings(*_args):
        return {"status": "unavailable", "events": []}
    monkeypatch.setattr(watchlist, "fetch_earnings_range", earnings)
    assert fvs.thesis_candidates(db, [company.id]) == {}
    home = valuation.fair_values("AAPL", db)["items"]["AAPL"]
    monitor = asyncio.run(watchlist.watchlist_monitor(tickers="AAPL", db=db))["items"]["AAPL"]
    assert home["value"] is None and home["source"] is None
    assert monitor["fair_value"] is None and monitor["fair_value_source"] is None
    assert thesis.expected_value == Decimal("119.92")


def test_latest_blocked_model_overrides_old_publishable_and_other_tenant(saved):
    db, company, _, other = saved
    model(db, company, publishable=True)
    model(db, company, publishable=False, version=2)
    owner = db.info["tenant_id"]
    db.info["tenant_id"] = other.id
    model(db, company, publishable=True, version=99, tenant_id=other.id)
    db.info["tenant_id"] = owner
    assert fvs.thesis_candidates(db, [company.id]) == {}


def test_single_live_read_does_not_choose_archived_thesis(saved, monkeypatch):
    db, company, _, _ = saved
    model(db, company, publishable=False)
    class Engine:
        def value_company(self, *_):
            return {"expected_value": 200, "publishable": True}
    monkeypatch.setattr("app.services.valuation_service.ValuationService", Engine)
    reading = fvs.resolve_fair_value(db, company)
    assert reading["source"] == "motor" and reading["value"] == 200


def test_publishable_thesis_remains_available_and_can_unblock(saved):
    db, company, thesis, _ = saved
    model(db, company, publishable=False)
    assert fvs.thesis_candidates(db, [company.id]) == {}
    model(db, company, publishable=True, version=2)
    candidate = fvs.thesis_candidates(db, [company.id])[company.id]
    assert candidate.value == 119.92 and candidate.thesis_version == thesis.version


def test_inferred_inputs_remain_blocked_even_when_model_publishable(saved):
    db, company, thesis, _ = saved
    model(db, company, publishable=True)
    thesis.valuation_basis = {"inferred_inputs_used": ["revenue"]}
    db.commit()
    assert fvs.thesis_candidates(db, [company.id]) == {}


def test_publicable_model_does_not_allow_fallback_to_older_thesis(saved):
    db, company, thesis, _ = saved
    model(db, company, publishable=True)
    db.add(ThesisVersion(tenant_id=thesis.tenant_id, company_id=company.id, version=4,
        status="published", thesis_markdown="new", executive_summary="new",
        expected_value=Decimal("999"), valuation_basis={"inferred_inputs_used": ["revenue"]}))
    db.commit()
    assert fvs.thesis_candidates(db, [company.id]) == {}


def test_blocked_thesis_allows_independent_persisted_engine_not_archived_value(saved):
    from app.models import ValuationModel, ValuationOutput

    db, company, _, _ = saved
    model(db, company, publishable=False)
    engine = ValuationModel(tenant_id=db.info["tenant_id"], company_id=company.id,
        model_type="dcf", version=1, status="final", calculation_trace={})
    db.add(engine)
    db.flush()
    db.add(ValuationOutput(tenant_id=db.info["tenant_id"], valuation_model_id=engine.id,
        scenario="base", value_per_share=200, output_payload={"expected_value": 200}))
    db.commit()
    reading = fvs.resolve_fair_values(db, [company])[company.id]
    assert reading["source"] == "motor" and reading["value"] == 200
