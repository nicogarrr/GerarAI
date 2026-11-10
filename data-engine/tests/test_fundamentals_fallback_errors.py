"""Fallback failures preserve honest state and roll back partial source writes."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact
from app.services import fundamentals_fallback as ff
from app.valuation.financial_snapshot import FinancialSnapshotBuilder


@pytest.fixture
def source_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.info["tenant_id"] = "fallback-test"
            company = Company(
                ticker="FALLBACK",
                name="Fallback Test",
                exchange="X",
                currency="EUR",
                sector="S",
                industry="I",
                company_type="research_candidate",
                valuation_model="unassigned",
                special_sources=[],
                special_risks=[],
                factor_tags=[],
            )
            db.add(company)
            db.commit()
            yield db, company
    finally:
        engine.dispose()


def _partial_fact(db, company, source):
    db.add(
        FinancialFact(
            company_id=company.id,
            metric="revenue",
            value=42,
            unit="EUR",
            period="2025-12-31:FY",
            fiscal_year=2025,
            fiscal_quarter="FY",
            source_type=source,
        )
    )
    db.flush()


def _count(db):
    return db.scalar(select(func.count()).select_from(FinancialFact))


def test_both_non_sec_sources_fail_without_leaving_facts(source_db):
    db, company = source_db
    calls = []

    def esef(db, company):
        calls.append("esef")
        _partial_fact(db, company, "ESEF")
        raise RuntimeError("https://source.example?apikey=PRIVATE_TOKEN")

    def yahoo(db, company, *, commit):
        assert commit is False
        assert _count(db) == 0
        calls.append("yahoo")
        _partial_fact(db, company, "YAHOO_FUNDAMENTALS")
        raise TimeoutError("https://source.example?token=PRIVATE_TOKEN")

    sec = {"status": "pending", "detail": "no SEC"}
    result = ff._non_sec_fallback(db, company, sec, [], esef_refresh=esef, yahoo_full=yahoo)
    assert calls == ["esef", "yahoo"] and _count(db) == 0
    assert result["status"] == "pending" and result["detail"] == "no SEC"
    assert [step["source"] for step in result["fallback_chain"]] == [ff.ESEF_LIVE_LABEL, ff.YAHOO_FULL_LABEL]
    assert all(
        step["status"] == "error" and "PRIVATE_TOKEN" not in step["detail"]
        for step in result["fallback_chain"]
    )
    assert db.get(Company, company.id) is company


def test_gap_snapshot_failure_skips_source(source_db, monkeypatch):
    db, company = source_db

    def broken(*args):
        raise LookupError("snapshot unavailable")

    def forbidden(*args, **kwargs):
        pytest.fail("no refresh without a starting snapshot")

    monkeypatch.setattr(FinancialSnapshotBuilder, "build", broken)
    assert ff.fill_bridge_gaps(db, company, refresh=forbidden) == {"status": "error", "detail": "LookupError"}
    assert _count(db) == 0


def test_gap_refresh_failure_rolls_back_and_redacts(source_db, monkeypatch):
    db, company = source_db
    monkeypatch.setattr(
        FinancialSnapshotBuilder,
        "build",
        lambda *args: SimpleNamespace(missing_inputs=["net_debt", "shares_diluted", "revenue"]),
    )

    def broken(db, company, *, commit):
        assert commit is False
        _partial_fact(db, company, "YAHOO_FUNDAMENTALS")
        raise RuntimeError("https://source.example?apikey=PRIVATE_TOKEN")

    result = ff.fill_bridge_gaps(db, company, refresh=broken)
    assert result["status"] == "error" and result["source"] == ff.YAHOO_LABEL
    assert result["wanted"] == ["net_debt", "shares_diluted"]
    assert "PRIVATE_TOKEN" not in result["detail"] and len(result["detail"]) <= 200
    assert _count(db) == 0 and db.get(Company, company.id) is company


def test_second_snapshot_failure_does_not_invent_closed_gaps(source_db, monkeypatch):
    db, company = source_db
    calls = []

    def build(*args):
        calls.append("snapshot")
        if len(calls) > 1:
            raise RuntimeError("post-refresh build failed")
        return SimpleNamespace(missing_inputs=["shares_diluted", "net_debt", "revenue"])

    monkeypatch.setattr(FinancialSnapshotBuilder, "build", build)
    result = ff.fill_bridge_gaps(
        db, company, refresh=lambda *args, **kwargs: {"facts_imported": 2, "symbol": "FALLBACK"}
    )
    assert calls == ["snapshot", "snapshot"]
    assert result["status"] == "ok" and result["mode"] == "huecos"
    assert result["wanted"] == result["still_missing"] == ["net_debt", "shares_diluted"]
    assert result["closed"] == [] and result["facts_imported"] == 2


def test_disabled_gap_refresh_never_builds_snapshot(source_db, monkeypatch):
    db, company = source_db
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: SimpleNamespace(yahoo_bridge_gaps_enabled=False)
    )

    def forbidden(*args):
        pytest.fail("disabled mode must not build a snapshot")

    monkeypatch.setattr(FinancialSnapshotBuilder, "build", forbidden)
    assert ff.fill_bridge_gaps(db, company) == {"status": "desactivado"}
