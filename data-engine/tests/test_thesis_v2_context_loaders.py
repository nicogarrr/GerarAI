"""Thesis context reads from real SQLite rows, with valuation/provider seams local."""

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import AnalystNote, DeclaredInputValue
from app.models.entities import Base, Company, Document, FinancialFact, Tenant
from app.services import insider_summary, official_catalysts, shareholder_irr_service
from app.services.expert_team import thesis_v2 as thesis
from app.services.expert_team import thesis_v2_experts
from app.valuation.shareholder_irr import Drivers, StartingPoint

DAY = date(2026, 11, 9)


@pytest.fixture
def store():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id="fixture-tenant"))
        db.flush()
        db.info["tenant_id"] = 1
        company = Company(
            ticker="FIXTURE",
            name="Fixture Corp /ON/",
            exchange="NYSE",
            currency="USD",
            sector="Materials",
            industry="Materials",
            company_type="quality",
            valuation_model="unassigned",
            factor_tags=[],
            special_sources=[],
            special_risks=[],
        )
        db.add(company)
        db.flush()
        yield db, company
    engine.dispose()


def declared(company, key, **kw):
    values = dict(
        company_id=company.id,
        tenant_id=1,
        input_key=key,
        base=Decimal("10000000"),
        unit="USD",
        method="analyst",
        status="estimado",
        source_url="https://fixture.invalid/source",
        source_quote="Recorded fixture quote",
        metadata_={},
    )
    values.update(kw)
    return DeclaredInputValue(**values)


def note(company, firm, day, target, **kw):
    values = dict(
        company_id=company.id,
        tenant_id=1,
        ticker=company.ticker,
        firm=firm,
        firm_key=firm.lower(),
        note_date=day,
        pt_new=target,
        currency="USD",
        action="maintain",
        source_type="news",
        verification="fragmento",
        dedupe_key=f"{firm}-{day}-{target}",
        source_url="https://fixture.invalid/note",
    )
    values.update(kw)
    return AnalystNote(**values)


def test_point_rows_use_latest_id_per_metric_year_and_skip_segments_and_bad_periods(store):
    db, company = store
    for metric, period, value in [
        ("total_debt", "2025-12-31:FY", 10_000_000),
        ("total_debt", "2025-12-31:FY", 20_000_000),
        ("total_debt", "2024-12-31:FY", 5_000_000),
        ("cash_and_equivalents", "2025-12-31:FY", 2_000_000),
        ("total_debt", "bad-date", 99_000_000),
        ("revenue", "2025-12-31:FY", 99_000_000),
    ]:
        db.add(FinancialFact(company_id=company.id, tenant_id=1, metric=metric, period=period, value=value))
    segment = Document(
        company_id=company.id,
        tenant_id=1,
        title="Segment fixture",
        source_type="test",
        metadata_={"segment": "one"},
    )
    db.add(
        FinancialFact(
            company_id=company.id,
            tenant_id=1,
            metric="total_debt",
            period="2025-12-31:FY",
            value=99_000_000,
            source=segment,
        )
    )
    db.flush()
    assert thesis._point_by_year(db, company, ["total_debt", "cash_and_equivalents"]) == {
        "total_debt": {2025: 20.0, 2024: 5.0},
        "cash_and_equivalents": {2025: 2.0},
    }


def test_analyst_rows_exclude_superseded_and_consensus_and_keep_source_fields(store):
    db, company = store
    db.add_all(
        [
            declared(
                company, "analyst.revenue.2027.a", analyst_firm="Firm A", as_of=DAY, metadata_={"year": 2027}
            ),
            declared(
                company,
                "analyst.ebitda.2027.b",
                analyst_firm=None,
                metadata_={"firm": "Firm B", "metric": "operating_income", "year": 2027},
            ),
            declared(company, "analyst.revenue.2028.c", metadata_={"consensus": True}),
            declared(company, "analyst.revenue.2029.d", superseded_at=datetime.now(UTC)),
            declared(company, "manual.revenue.2030", method="manual"),
        ]
    )
    db.flush()
    rows, targets = thesis.analyst_estimates(db, company, DAY)
    assert targets == []
    assert [(r["firm"], r["metric"], r["year"], r["value"], r["as_of"]) for r in rows] == [
        ("Firm B", "operating_income", 2027, 10.0, ""),
        ("Firm A", "revenue", 2027, 10.0, DAY.isoformat()),
    ]
    assert all(
        r["url"] == "https://fixture.invalid/source" and r["quote"] == "Recorded fixture quote" for r in rows
    )


def test_target_rows_use_last_note_per_firm_and_one_year_inclusive_boundary(store):
    db, company = store
    db.add_all(
        [
            note(company, "Firm A", DAY - timedelta(days=10), 100),
            note(company, "Firm A", DAY, 80),
            note(company, "Firm B", DAY - timedelta(days=365), 90, currency=None),
            note(company, "Too old", DAY - timedelta(days=366), 1),
            note(company, "No target", DAY, None),
            note(company, "Other ticker", DAY, 2, ticker="OTHER"),
        ]
    )
    db.flush()
    rows, targets = thesis.analyst_estimates(db, company, DAY)
    assert rows == []
    assert [(t["firm"], t["target"], t["currency"]) for t in targets] == [
        ("Firm A", 80.0, "USD"),
        ("Firm B", 90.0, ""),
    ]
    assert targets[0]["date"] == DAY.isoformat() and targets[0]["url"] == "https://fixture.invalid/note"


def test_guidance_rows_preserve_zero_bounds_trim_quote_and_ignore_superseded(store):
    db, company = store
    db.add_all(
        [
            declared(
                company,
                "guidance.revenue.fy2027",
                method="extract",
                status="oficial",
                low=0,
                high=12_000_000,
                source_quote="Q" * 450,
                as_of=DAY,
                metadata_={"document_title": "Fixture release"},
            ),
            declared(
                company, "guidance.ebitda.fy2027", method="extract", status="oficial", low=None, high=None
            ),
            declared(company, "guidance.revenue.fy2026", superseded_at=datetime.now(UTC)),
            declared(company, "analyst.revenue.2027"),
        ]
    )
    db.flush()
    rows = thesis.company_guidance_rows(db, company)
    assert [r["key"] for r in rows] == ["guidance.ebitda.fy2027", "guidance.revenue.fy2027"]
    assert rows[0]["low"] is rows[0]["high"] is rows[0]["as_of"] is None
    row = rows[1]
    assert (row["metric"], row["period"], row["low"], row["base"], row["high"]) == (
        "revenue",
        "fy2027",
        0.0,
        10_000_000.0,
        12_000_000.0,
    )
    assert row["quote"] == "Q" * 400 and row["document"] == "Fixture release"
    assert row["as_of"] == DAY.isoformat() and row["url"] == "https://fixture.invalid/source"


@pytest.mark.parametrize("status", ["sin_datos", "error"])
def test_context_without_valuation_returns_empty_without_reading_optional_sources(store, monkeypatch, status):
    db, company = store
    value = {"status": status}
    monkeypatch.setattr(shareholder_irr_service, "value_company", lambda *a, **kw: value)
    passages = Mock(side_effect=AssertionError("must not read optional data"))
    monkeypatch.setattr(thesis, "evidence_passages", passages)
    ctx = thesis.build_context(db, company, today=DAY)
    assert ctx.valuation is value and value["as_of"] == DAY.isoformat()
    assert ctx.company == "Fixture Corp"
    assert ctx.history == ctx.peers == ctx.switches == ctx.passages == [] and ctx.implied_growth is None
    passages.assert_not_called()


@pytest.mark.parametrize("guide,fail_optional", [(True, False), (False, False), (False, True)])
def test_context_composes_guidance_analyst_fallback_and_optional_source_failure(
    store, monkeypatch, guide, fail_optional
):
    db, company = store
    point = asdict(StartingPoint(price=10, shares_diluted=1, revenue=100, ebitda=10, debt=20))
    point["net_debt"] = 20
    value = {
        "status": "ok",
        "starting_point": point,
        "citations": {"annual": {}},
        "discount_rate": 0.1,
        "scenarios": {"base": {"drivers": asdict(Drivers(organic_growth=0.02, organic_growth_late=0.01))}},
    }
    monkeypatch.setattr(shareholder_irr_service, "value_company", lambda *a, **kw: value)
    monkeypatch.setattr(thesis, "implied_growth", lambda *a, **kw: 0.04)
    monkeypatch.setattr(thesis, "kill_switches", lambda *a: [{"key": "base-switch"}])
    monkeypatch.setattr(thesis, "estimate_switches", lambda *a: [{"key": "guide-switch"}])
    if guide:
        db.add(declared(company, "guidance.revenue.fy2027"))
    else:
        db.add(declared(company, "analyst.revenue.2027", analyst_firm="Fixture analyst"))
    db.flush()
    insider = (
        Mock(side_effect=RuntimeError("local failure"))
        if fail_optional
        else Mock(return_value={"status": "sin_datos"})
    )
    monkeypatch.setattr(insider_summary, "insider_summary", insider)
    experts = (
        Mock(side_effect=RuntimeError("local failure"))
        if fail_optional
        else Mock(return_value={"fixture": "expert"})
    )
    monkeypatch.setattr(thesis_v2_experts, "expert_block", experts)
    catalysts = (
        Mock(side_effect=RuntimeError("local failure"))
        if fail_optional
        else Mock(return_value=[{"fixture": "catalyst"}])
    )
    monkeypatch.setattr(official_catalysts, "catalysts_for", catalysts)
    ctx = thesis.build_context(db, company, today=DAY, tenant_id=1)
    assert (
        ctx.implied_growth == 0.04
        and ctx.optional["deuda_balance"] == "deuda neta superior a una vez el EBITDA"
    )
    assert ctx.switches == [{"key": "base-switch"}, {"key": "guide-switch"}]
    assert ctx.optional["consenso_guia"] == (
        "la empresa da previsiones citadas en sus notas de resultados"
        if guide
        else "hay estimaciones de analistas citadas de la prensa"
    )
    assert bool(ctx.guidance) is guide and bool(ctx.analysts) is not guide
    assert ctx.insiders is None
    assert ctx.experts == (None if fail_optional else {"fixture": "expert"})
    assert ctx.catalysts == ([] if fail_optional else [{"fixture": "catalyst"}])
    experts.assert_called_once_with(db, company, 1)
    insider.assert_called_once_with(db, company.ticker, as_of=DAY)
