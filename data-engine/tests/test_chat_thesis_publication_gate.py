"""Archived valuation prose must not become current chat evidence."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FundamentalModelVersion, Tenant, ThesisVersion
from app.services.chat_service import ChatService
from app.services.research_assistant_service import _thesis_citations


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


def response(db, question):
    return ChatService()._deterministic_answer(db, question, "company", "AAPL")


@pytest.mark.parametrize("question", ["tesis AAPL", "rating AAPL", "riesgos AAPL"])
def test_blocked_model_hides_prose_rating_and_figures_in_chat(saved, question):
    db, company, thesis, _ = saved
    model(db, company, publishable=False)
    result = response(db, question)
    text = result.model_dump_json()
    for sentinel in ("ARCHIVED_PROSE", "119.92", "119,92", "-65,1", "rating compra", "87/100"):
        assert sentinel not in text
    assert "modelo no es publicable" in result.answer
    assert "2026-10-01" in result.answer
    assert thesis.executive_summary.startswith("ARCHIVED_PROSE")
    assert thesis.expected_value == Decimal("119.92")


def test_blocked_model_hides_assistant_citation_payload(saved):
    db, company, thesis, _ = saved
    model(db, company, publishable=False)
    citations = _thesis_citations(db, company, db.info["tenant_id"])
    assert citations and citations[0]["as_of"] == "2026-10-01"
    excerpt = citations[0]["excerpt"]
    assert "modelo no es publicable" in excerpt
    for sentinel in ("ARCHIVED_PROSE", "119,92", "-65,1", "rating buy"):
        assert sentinel not in excerpt
    assert thesis.executive_summary.startswith("ARCHIVED_PROSE")


def test_publishable_model_preserves_existing_response(saved):
    db, company, _, _ = saved
    model(db, company, publishable=True)
    assert "ARCHIVED_PROSE" in response(db, "tesis AAPL").answer
    assert "ARCHIVED_PROSE" in _thesis_citations(db, company, db.info["tenant_id"])[0]["excerpt"]


def test_latest_model_wins_and_other_tenant_cannot_unblock(saved):
    db, company, _, other = saved
    model(db, company, publishable=True)
    model(db, company, publishable=False, version=2)
    owner = db.info["tenant_id"]
    db.info["tenant_id"] = other.id
    model(db, company, publishable=True, version=99, tenant_id=other.id)
    db.info["tenant_id"] = owner
    assert "ARCHIVED_PROSE" not in response(db, "tesis AAPL").answer
    assert "ARCHIVED_PROSE" not in _thesis_citations(db, company, db.info["tenant_id"])[0]["excerpt"]


def test_inferred_input_guard_also_covers_visible_summary(saved):
    db, company, thesis, _ = saved
    model(db, company, publishable=True)
    thesis.valuation_basis = {"inferred_inputs_used": ["revenue"]}
    db.commit()
    assert "ARCHIVED_PROSE" not in response(db, "tesis AAPL").answer
    assert "ARCHIVED_PROSE" not in _thesis_citations(db, company, db.info["tenant_id"])[0]["excerpt"]


def test_blocked_context_never_includes_archived_section_titles(saved):
    from app.models import ThesisSection

    db, company, thesis, _ = saved
    model(db, company, publishable=False)
    db.add(ThesisSection(tenant_id=db.info["tenant_id"], thesis_version_id=thesis.id, company_id=company.id,
        section_key="analysis", title="ARCHIVED_SECTION_TITLE 119,92", body="ARCHIVED_SECTION_BODY"))
    db.commit()
    assert "ARCHIVED_SECTION" not in response(db, "tesis AAPL").model_dump_json()


def test_new_publishable_model_unblocks_without_changing_stored_thesis(saved):
    db, company, thesis, _ = saved
    model(db, company, publishable=False)
    assert "ARCHIVED_PROSE" not in response(db, "tesis AAPL").answer
    model(db, company, publishable=True, version=2)
    assert "ARCHIVED_PROSE" in response(db, "tesis AAPL").answer
    assert "ARCHIVED_PROSE" in _thesis_citations(db, company, db.info["tenant_id"])[0]["excerpt"]
    db.refresh(thesis)
    assert thesis.rating == "buy" and thesis.expected_value == Decimal("119.92")


def test_missing_model_fails_closed(saved):
    db, company, _, _ = saved
    result = response(db, "tesis AAPL")
    assert "ARCHIVED_PROSE" not in result.model_dump_json()
    assert "modelo publicable verificado" in result.answer
    assert "ARCHIVED_PROSE" not in _thesis_citations(db, company, db.info["tenant_id"])[0]["excerpt"]
