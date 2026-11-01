"""Monitor batching preserves values while query count stays constant."""
import asyncio
from datetime import date, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes import watchlist
from app.models.entities import Base, Company, FundamentalModelVersion, MarketPrice, ThesisVersion


def test_monitor_twenty_companies_has_constant_query_count(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    today = date.today()
    for index in range(20):
        company = Company(ticker=f"BATCH{index}", name="Batch", exchange="NYSE", currency="USD",
                          company_type="listed", valuation_model="dcf")
        db.add(company)
        db.flush()
        db.add(ThesisVersion(company_id=company.id, version=1, status="published",
                             expected_value=150, thesis_markdown="t", executive_summary="s"))
        db.add(ThesisVersion(company_id=company.id, version=2, status="draft",
                             expected_value=900, thesis_markdown="t", executive_summary="s"))
        db.add(FundamentalModelVersion(
            company_id=company.id, version=1, engine_version="test", algorithm_version="test",
            framework_key="dcf", horizon_years=10, status="ok", publishable=True,
            input_fingerprint="input", forecast_fingerprint="forecast",
            market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
        ))
        for days, price in ((400, 1), (20, 80), (1, 100), (0, 110)):
            db.add(MarketPrice(company_id=company.id, date=today-timedelta(days=days), close=price))
    db.commit()
    async def earnings(*args):
        return {"status": "unavailable", "events": []}
    monkeypatch.setattr(watchlist, "fetch_earnings_range", earnings)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    result = asyncio.run(watchlist.watchlist_monitor(
        tickers=','.join(f"BATCH{i}" for i in range(20)), db=db))
    # Una query batch adicional verifica publicación del modelo y otra lee los
    # splits (mínimo de 52 semanas desde el último split); coste constante.
    assert len(statements) == 9
    assert len(result["items"]) == 20
    for row in result["items"].values():
        assert row["low_52w"] == 80
        assert row["low_52w_date"] == (today-timedelta(days=20)).isoformat()
        assert row["low_52w_sessions"] == 3
        assert row["last_close"] == 110
        assert row["last_close_date"] == today.isoformat()
        assert row["fair_value"] == 150
        assert row["fair_value_thesis_version"] == 1
        assert row["valuation_side"] == "infravalorada"
    statements.clear()
    asyncio.run(watchlist.watchlist_monitor(tickers="BATCH0", db=db))
    assert len(statements) == 9
    db.close()


def test_latest_published_inferred_thesis_is_not_replaced_by_older_fair_value(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    company = Company(ticker="INFERRED", name="Inferred", exchange="NYSE", currency="USD",
                      company_type="listed", valuation_model="dcf")
    db.add(company)
    db.flush()
    for version, basis in ((1, {}), (2, {"inferred_inputs_used": ["margin"]})):
        db.add(ThesisVersion(company_id=company.id, version=version, status="published",
                             expected_value=150, valuation_basis=basis,
                             thesis_markdown="t", executive_summary="s"))
    db.commit()
    async def earnings(*args):
        return {"status": "unavailable", "events": []}
    monkeypatch.setattr(watchlist, "fetch_earnings_range", earnings)
    out = asyncio.run(watchlist.watchlist_monitor(tickers="INFERRED", db=db))
    row = out["items"]["INFERRED"]
    assert row["fair_value"] is None
    assert row["fair_value_thesis_version"] is None
    assert row["low_52w"] is None
    assert row["low_52w_sessions"] == 0
    db.close()
