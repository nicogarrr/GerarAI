"""Archived valuation prose must not escape through downloadable exports."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.thesis import debate_thesis_endpoint
from app.models.entities import Base, Company, FundamentalModelVersion, Tenant, ThesisVersion


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
def test_debate_rejects_unpublishable_archive_before_provider_or_writes(saved, monkeypatch, publishable):
    import asyncio

    from fastapi import HTTPException

    from app.llm import free_interactive
    from app.models import ThesisSection
    from app.services import thesis_debate_service

    db, company, thesis, _ = saved
    if publishable is not None:
        model(db, company, publishable=publishable)
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr("app.api.routes.thesis.run_in_threadpool", direct)
    before = db.query(ThesisSection).count()
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Provider/debate must not receive archived prose")
    monkeypatch.setattr(free_interactive, "create_free_interactive_provider", forbidden)
    monkeypatch.setattr(thesis_debate_service, "debate_thesis", forbidden)
    with pytest.raises(HTTPException) as error:
        asyncio.run(debate_thesis_endpoint(company.ticker, db))
    assert error.value.status_code == 409
    assert "archivada v3" in error.value.detail
    assert "2026-10-01" in error.value.detail
    assert db.query(ThesisSection).count() == before
    db.refresh(thesis)
    assert thesis.thesis_markdown == "ARCHIVED_MEMO"


def test_publishable_debate_receives_original_and_persists(saved, monkeypatch):
    import asyncio

    from app.llm import free_interactive
    from app.services import thesis_debate_service

    db, company, thesis, _ = saved
    model(db, company, publishable=True)
    # Threadpool is not the subject under test; keep SQLite on its own thread.
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr("app.api.routes.thesis.run_in_threadpool", direct)
    seen = []
    async def debate(ticker, text, **kwargs):
        seen.append(text)
        return {"verdict": "hold", "verdict_rationale": "test", "bull_case": "bull",
                "bear_case": "bear", "key_disagreements": [], "model": "stub", "llm_calls": 0, "degraded": False,
                "bull_confidence": 0.8, "bear_confidence": 0.6, "disagreement_score": 0.2}
    monkeypatch.setattr(free_interactive, "create_free_interactive_provider", lambda: object())
    monkeypatch.setattr(thesis_debate_service, "debate_thesis", debate)
    result = asyncio.run(debate_thesis_endpoint(company.ticker, db))
    assert seen == ["ARCHIVED_MEMO"]
    assert result["persisted"] is True
