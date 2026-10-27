"""Archived valuation prose must not escape through downloadable exports."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.thesis import latest_thesis, thesis_versions
from app.models.entities import Base, Company, FundamentalModelVersion, Tenant, ThesisVersion
from app.services.company_snapshot_service import CompanySnapshotService


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
def test_latest_and_versions_withhold_every_free_text_field(saved, monkeypatch, publishable):
    from app.services.thesis_service import ThesisService

    db, company, thesis, _ = saved
    if publishable is not None:
        model(db, company, publishable=publishable)
    thesis.hypothesis = "ARCHIVED_HYPOTHESIS"
    thesis.catalysts = ["ARCHIVED_CATALYST"]
    thesis.invalidation_criteria = ["ARCHIVED_CRITERION"]
    thesis.narrative_sections = [{"titulo": "ARCHIVED_TITLE", "parrafos": ["ARCHIVED_PARAGRAPH"]}]
    db.commit()
    monkeypatch.setattr(ThesisService, "data_freshness", lambda *_, **__: None)
    for result in (latest_thesis(company.ticker, db), *thesis_versions(company.ticker, 1, 25, db)):
        from app.schemas import ThesisOut

        result = ThesisOut.model_validate(result).model_dump()
        text = str(result)
        assert "ARCHIVED_" not in text
        assert "119.92" not in text and "-0.651" not in text
        assert result["rating"] == "insufficient_data"
        assert result["margin_of_safety_status"] == "withheld"
        assert "archivada v3" in result["executive_summary"]
    db.refresh(thesis)
    assert thesis.executive_summary.startswith("ARCHIVED_")
    assert thesis.expected_value == Decimal("119.92")


def test_snapshot_single_and_batch_withhold_summary_and_figures(saved):
    db, company, thesis, _ = saved
    model(db, company, publishable=False)
    for snapshot in (CompanySnapshotService().build(db, company),
                     CompanySnapshotService().build_many(db, [company])[company.id]):
        text = snapshot.latest_thesis.model_dump_json()
        assert "ARCHIVED_" not in text and "119.92" not in text and "-0.651" not in text
        assert snapshot.valuation_summary.expected_value is None
        assert snapshot.valuation_summary.archived_margin_of_safety is None
        assert snapshot.latest_thesis.rating == "insufficient_data"
        assert "archivada v3" in snapshot.latest_thesis.executive_summary


def test_publishable_api_and_snapshot_preserve_prose(saved, monkeypatch):
    from app.services.thesis_service import ThesisService

    db, company, _, _ = saved
    model(db, company, publishable=True)
    monkeypatch.setattr(ThesisService, "data_freshness", lambda *_, **__: None)
    assert "ARCHIVED_PROSE" in latest_thesis(company.ticker, db)["executive_summary"]
    assert "ARCHIVED_PROSE" in CompanySnapshotService().build(db, company).latest_thesis.executive_summary
