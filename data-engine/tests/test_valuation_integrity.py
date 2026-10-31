"""Tests for valuation integrity: no bootstrap fair values, no $100 price, engine registry."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

import main
from app.core.database import SessionLocal, init_db
from app.models import (
    Claim,
    Company,
    FinancialFact,
    FundamentalModelVersion,
    MarketPrice,
    Position,
    ThesisVersion,
    ValuationModel,
)
from app.seed import seed
from app.services.thesis_graph_service import ThesisGraphService
from app.services.thesis_service import ThesisService
from app.services.valuation_service import ValuationService
from app.valuation.engines import resolve_engine_key
from app.valuation.financial_snapshot import FinancialSnapshotBuilder
from tests.auth_helpers import csrf_client


def test_asts_without_facts_returns_insufficient_data_not_bootstrap_fair_value():
    init_db()
    seed()
    client = csrf_client(main.app)

    valuation = client.get("/api/valuation/ASTS")
    assert valuation.status_code == 200
    payload = valuation.json()

    assert payload["status"] == "insufficient_data"
    assert payload["publishable"] is False
    assert payload["expected_value"] is None
    assert payload["base_value"] is None
    assert payload["trace"]["input_source"] == "insufficient_data"
    assert "bootstrap" not in (payload["trace"].get("input_source") or "")
    assert payload["missing_inputs"]
    assert payload["trace"]["engine"] == "pre_revenue"


def test_missing_market_price_is_null_never_100():
    init_db()
    seed()
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "NOW"))
        assert company is not None
        # Remove any demo prices for this company
        for position in db.scalars(select(Position).where(Position.company_id == company.id)).all():
            position.market_price = Decimal("0")
        for price in db.scalars(select(MarketPrice).where(MarketPrice.company_id == company.id)).all():
            db.delete(price)
        db.commit()

        result = ValuationService().value_company(db, company)
        assert result["current_price"] is None
        assert result["current_price"] != 100.0
        # Without facts, also insufficient
        assert result["status"] == "insufficient_data" or result.get("margin_of_safety") is None
    finally:
        db.close()


def test_engine_registry_routes_portfolio_names():
    init_db()
    seed()
    db = SessionLocal()
    try:
        mapping = {
            "ASTS": "pre_revenue",
            "MSFT": "standard_dcf",
            "BN": "holding_company",
            "BABA": "holding_company",
            "CCJ": "commodity",
            "RKLB": "sotp",
        }
        for ticker, expected in mapping.items():
            company = db.scalar(select(Company).where(Company.ticker == ticker))
            assert company is not None, ticker
            assert resolve_engine_key(company) == expected, ticker
    finally:
        db.close()


def test_snapshot_builder_rejects_mixed_fiscal_years():
    init_db()
    seed()
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "MSFT"))
        assert company is not None
        # Clean prior facts
        for fact in db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id)).all():
            db.delete(fact)
        db.flush()

        db.add_all(
            [
                FinancialFact(
                    company_id=company.id,
                    metric="revenue",
                    value=Decimal("1000"),
                    unit="USD",
                    period="FY2025",
                    fiscal_year=2025,
                    fiscal_quarter="FY",
                    source_type="test",
                ),
                FinancialFact(
                    company_id=company.id,
                    metric="free_cash_flow",
                    value=Decimal("250"),
                    unit="USD",
                    period="FY2024",
                    fiscal_year=2024,
                    fiscal_quarter="FY",
                    source_type="test",
                ),
                FinancialFact(
                    company_id=company.id,
                    metric="shares_diluted",
                    value=Decimal("100"),
                    unit="shares",
                    period="FY2025",
                    fiscal_year=2025,
                    fiscal_quarter="FY",
                    source_type="test",
                ),
            ]
        )
        db.commit()

        snapshot = FinancialSnapshotBuilder().build(db, company)
        assert snapshot.facts["revenue"].fiscal_year == 2025
        assert "free_cash_flow" not in snapshot.facts
        assert any("free_cash_flow" in w for w in snapshot.warnings)
        # Missing FCF/margin → not coherent for DCF
        assert "normalized_fcf_or_fcf_margin" in snapshot.missing_inputs
    finally:
        db.close()


def test_thesis_version_appears_in_markdown_title():
    init_db()
    seed()
    client = csrf_client(main.app)

    # Force two versions
    first = client.post("/api/thesis/generate", json={"ticker": "ASTS", "force_new_version": True})
    assert first.status_code == 200
    v1 = first.json()["version"]
    assert f"Tesis de ASTS — v{v1}" in first.json()["thesis_markdown"]

    second = client.post("/api/thesis/generate", json={"ticker": "ASTS", "force_new_version": True})
    assert second.status_code == 200
    v2 = second.json()["version"]
    assert v2 == v1 + 1
    assert f"Tesis de ASTS — v{v2}" in second.json()["thesis_markdown"]
    assert second.json()["status"] == "insufficient_data"
    assert second.json()["bear_value"] is None
    assert second.json()["expected_value"] is None
    assert "no publicable" in second.json()["executive_summary"]


def test_thesis_generation_rolls_back_everything_when_graph_build_fails(monkeypatch):
    init_db()
    seed()
    db = SessionLocal()
    try:
        models = (ThesisVersion, ValuationModel, FundamentalModelVersion, Claim)
        before = {
            model.__tablename__: db.scalar(select(func.count()).select_from(model))
            for model in models
        }

        def fail_graph(*args, **kwargs):
            raise RuntimeError("graph build failed")

        monkeypatch.setattr(ThesisGraphService, "build", fail_graph)
        with pytest.raises(RuntimeError, match="graph build failed"):
            ThesisService().generate(db, "ASTS", force_new_version=True)

        after = {
            model.__tablename__: db.scalar(select(func.count()).select_from(model))
            for model in models
        }
        assert after == before
    finally:
        db.close()
