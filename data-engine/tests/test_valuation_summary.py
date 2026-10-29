from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, Document, FinancialFact, FundamentalModelVersion, FundamentalValuationSnapshot
from app.models.entities import Base
from app.services import valuation_summary as vs
from app.services.financial_ingestion_service import SEC_METRIC_MAP


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def company(db):
    row = Company(ticker="TEST", name="Test", exchange="NYSE", currency="USD", sector="Industrials", company_type="listed", valuation_model="dcf")
    db.add(row)
    db.flush()
    return row


def fact(db, c, doc, **kw):
    attrs = dict(company_id=c.id, metric="net_income", fiscal_year=2025, fiscal_quarter="FY", period="2025-12-31:FY", value=12, unit="USD", source_id=doc.id, source_type="SEC", tenant_id=1, is_reported=True, is_adjusted=False, filed=date(2026, 2, 1))
    attrs.update(kw)
    row = FinancialFact(**attrs)
    db.add(row)
    db.flush()
    return row


def test_empty_and_number_parsing(db):
    assert vs.build_summaries(db, []) == {}
    assert vs._number(None) is None
    assert vs._number("nan") is None
    assert vs._number("12.5") == 12.5


def test_source_selection_annual_tenant_and_future_guards(db, monkeypatch):
    c = company(db)
    doc = Document(company_id=c.id, title="10-K", source_url="https://www.sec.gov/filing", source_type="SEC", tenant_id=1)
    db.add(doc)
    db.flush()
    winner = fact(db, c, doc)
    fact(db, c, doc, source_type="FMP", value=999)
    fact(db, c, doc, source_type="SEC", fiscal_quarter="Q4", value=999)
    fact(db, c, doc, is_reported=False, value=999)
    fact(db, c, doc, is_adjusted=True, value=999)
    fact(db, c, doc, source_type="seed", value=999)
    fact(db, c, doc, period="unknown", value=999)
    fact(db, c, doc, period="2027-12-31:FY", value=999)
    fact(db, c, doc, filed=date(2027, 2, 1), value=999)
    fact(db, c, doc, source_id=None, value=999)
    db.info["tenant_id"] = 2
    fact(db, c, doc, tenant_id=2, value=999)
    db.info["tenant_id"] = 1
    original = vs.calculate_health
    captured = []
    def capture(facts, **kw):
        captured.extend(facts)
        return original(facts, **kw)
    monkeypatch.setattr(vs, "calculate_health", capture)
    out = vs.build_summaries(db, [c], today=date(2026, 10, 29))["TEST"]
    assert [f.id for f in captured] == [winner.id]
    assert out["health"]["piotroski"]["score"] is None
    assert out["reverse_dcf"]["status"] == "not_evaluable"
    assert out["fair_value"]["value"] is None
    assert not db.dirty and not db.new


def test_restated_inputs_and_separate_dated_reverse(db):
    c = company(db)
    doc = Document(company_id=c.id, title="10-K", source_url="https://www.sec.gov/filing", source_type="SEC", tenant_id=1)
    db.add(doc)
    db.flush()
    fact(db, c, doc)
    winner = fact(db, c, doc, filed=date(2026, 5, 1), value=14)
    model = FundamentalModelVersion(company_id=c.id, version=1, engine_version="test", algorithm_version="test", framework_key="dcf", horizon_years=5, status="ok", publishable=True, input_fingerprint="i", forecast_fingerprint="f", market_snapshot_fingerprint="m", valuation_snapshot_fingerprint="v", tenant_id=1)
    db.add(model)
    db.flush()
    snapshot = FundamentalValuationSnapshot(company_id=c.id, model_version_id=1, current_price=42, market_snapshot_fingerprint="m", valuation_snapshot_fingerprint="v", tenant_id=1, snapshot={"reverse_dcf": {"status": "ok", "required_revenue_growth": .08}})
    db.add(snapshot)
    db.flush()
    out = vs.build_summaries(db, [c], today=date(2026, 10, 29))["TEST"]
    assert out["reverse_dcf"]["required_revenue_growth"] == .08
    assert out["reverse_dcf"]["market_price"] == 42
    assert out["reverse_dcf"]["model_version_id"] == 1
    assert out["reverse_dcf"]["as_of"]
    signal = out["health"]["piotroski"]["signals"][0]
    assert signal["evidence"][0]["fact_id"] == winner.id
    model.publishable = False
    db.flush()
    assert vs.build_summaries(db, [c])["TEST"]["reverse_dcf"]["status"] == "not_evaluable"


def test_health_sec_concepts_are_exact():
    mapping = {metric: concepts for metric, concepts, _ in SEC_METRIC_MAP}
    assert mapping["current_assets"] == ["AssetsCurrent"]
    assert mapping["current_liabilities"] == ["LiabilitiesCurrent"]
    assert mapping["long_term_debt"] == ["LongTermDebtNoncurrent"]
    assert mapping["retained_earnings"] == ["RetainedEarningsAccumulatedDeficit"]


def test_summary_route_is_read_only_and_resolves_static_path(db):
    from app.api.routes.valuation import router, valuation_summaries

    company(db)
    out = valuation_summaries(tickers=" test,TEST,NO_SUCH_TICKER ", db=db)
    assert list(out["items"]) == ["TEST"]
    assert out["items"]["TEST"]["health"]["status"] == "not_evaluable"
    paths = [route.path for route in router.routes]
    assert paths.index("/summary") < paths.index("/{ticker}")
    assert not db.dirty and not db.new
