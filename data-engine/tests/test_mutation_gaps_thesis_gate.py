"""Publication-gate asserts that mutation testing (mutmut) showed were missing.

Mutants that dropped scenario values, the margin of safety or the scenario
probabilities from the withheld list survived the suite: an unverified
valuation could have leaked through any consumer of ``withhold_thesis_payload``.
A legacy thesis without tenant could also lose its publishable model unnoticed.
See docs/testing/mutation.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FundamentalModelVersion, Tenant, ThesisVersion
from app.services.thesis_publication_gate import (
    model_withheld_reason,
    thesis_withheld_reasons,
    withhold_thesis_payload,
)

WITHHELD_KEYS = (
    "bear_value",
    "base_value",
    "bull_value",
    "expected_value",
    "margin_of_safety",
    "archived_margin_of_safety",
    "margin_of_safety_convention",
    "hypothesis",
    "catalysts",
    "invalidation_criteria",
    "invalidation_rules",
    "scenario_probabilities",
    "narrative_sections",
)


def _thesis(**kw):
    base = dict(
        company_id=1,
        version=7,
        status="published",
        thesis_markdown="SECRET_MEMO",
        executive_summary="SECRET_SUMMARY",
        created_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    base.update(kw)
    return ThesisVersion(**base)


def test_withhold_payload_nulls_every_valuation_field():
    payload = {key: f"SECRET_{key}" for key in WITHHELD_KEYS}
    payload.update(
        rating="buy",
        executive_summary="SECRET_SUMMARY",
        thesis_markdown="SECRET_MEMO",
        valuation_withheld_reason=None,
        ticker="AAPL",
    )
    out = withhold_thesis_payload(payload, _thesis(), "motivo X")
    for key in WITHHELD_KEYS:
        assert out[key] is None, key
    assert out["rating"] == "insufficient_data"
    assert out["margin_of_safety_status"] == "withheld"
    assert out["executive_summary"] == "Tesis archivada v7 (2026-09-30): motivo X"
    assert out["thesis_markdown"] == out["executive_summary"]
    assert out["valuation_withheld_reason"] == "motivo X"
    assert out["ticker"] == "AAPL"
    assert "SECRET" not in repr(out)
    # The input dict is not mutated (callers may hold ORM-derived dicts).
    assert payload["base_value"] == "SECRET_base_value"


def test_withhold_payload_does_not_invent_absent_keys():
    out = withhold_thesis_payload({"rating": "buy", "executive_summary": "x"}, _thesis(), "r")
    assert "thesis_markdown" not in out
    assert "valuation_withheld_reason" not in out
    assert "base_value" not in out


def test_withhold_payload_without_reason_is_identity():
    payload = {"base_value": 1}
    assert withhold_thesis_payload(payload, _thesis(), None) is payload


def test_archived_notice_without_date():
    out = withhold_thesis_payload({}, _thesis(created_at=None), "r")
    assert out["executive_summary"] == "Tesis archivada v7 (fecha sin verificar): r"


def test_missing_model_reason_text_is_explicit():
    assert model_withheld_reason(_thesis(), None) == (
        "No hay un modelo publicable verificado; el texto y las cifras archivados no son análisis actual."
    )


def test_status_none_counts_as_draft():
    # A thesis with no status is an unpublished draft: shown when no model exists.
    assert model_withheld_reason(_thesis(status=None), None) is None


def _model(company_id, tenant_id, *, publishable, version=1):
    return FundamentalModelVersion(
        tenant_id=tenant_id,
        company_id=company_id,
        version=version,
        engine_version="t",
        algorithm_version="t",
        framework_key="dcf",
        horizon_years=10,
        status="ok",
        publishable=publishable,
        input_fingerprint=f"in-{version}",
        forecast_fingerprint="f",
        market_snapshot_fingerprint="m",
        valuation_snapshot_fingerprint="v",
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def test_batch_gate_matches_models_per_tenant_and_company_including_legacy(db):
    a = Tenant(external_id="a", name="A", status="active", metadata_={})
    b = Tenant(external_id="b", name="B", status="active", metadata_={})
    c1 = Company(
        ticker="AAA",
        name="A",
        exchange="NASDAQ",
        currency="USD",
        company_type="mature",
        valuation_model="dcf",
    )
    c2 = Company(
        ticker="BBB",
        name="B",
        exchange="NASDAQ",
        currency="USD",
        company_type="mature",
        valuation_model="dcf",
    )
    db.add_all([a, b, c1, c2])
    db.flush()
    legacy = _thesis(tenant_id=None, company_id=c1.id, expected_value=Decimal("10"))
    ta = _thesis(tenant_id=a.id, company_id=c1.id, version=2, expected_value=Decimal("10"))
    tb = _thesis(tenant_id=b.id, company_id=c1.id, version=3, expected_value=Decimal("10"))
    t2 = _thesis(tenant_id=a.id, company_id=c2.id, version=4, expected_value=Decimal("10"))
    db.add_all([legacy, ta, tb, t2])
    db.add_all(
        [
            _model(c1.id, None, publishable=True),
            _model(c1.id, a.id, publishable=True),
            _model(c1.id, b.id, publishable=True, version=1),
            _model(c1.id, b.id, publishable=False, version=2),  # newest wins: not publishable
        ]
    )
    db.commit()
    reasons = thesis_withheld_reasons(db, [legacy, ta, tb, t2])
    assert reasons[legacy.id] is None  # legacy tenant-less model found
    assert reasons[ta.id] is None
    assert reasons[tb.id]  # tenant B latest model is not publishable
    assert reasons[t2.id]  # company 2 has no model; company 1's must not count
    # Legacy thesis alone also finds its tenant-less model.
    assert thesis_withheld_reasons(db, [legacy]) == {legacy.id: None}
    assert thesis_withheld_reasons(db, []) == {}
