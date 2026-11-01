"""Watchlist: infra/sobrevalorada en valores de Londres (cierres en peniques).

El monitor comparaba el cierre guardado tal cual (2.650 peniques, Yahoo
«GBp») con el valor justo en libras (30 £): todo valor de Londres salía
«sobrevalorado» aunque cotizara por debajo de su valor justo.
"""
from datetime import date, timedelta

from fastapi.testclient import TestClient

import main
from app.core.database import SessionLocal, init_db
from app.models import Company, FundamentalModelVersion, MarketPrice, Tenant, ThesisVersion


def _seed(ticker: str, close: float, quote: str | None, currency: str, fair: float) -> None:
    init_db()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).first()
        company = db.query(Company).filter(Company.ticker == ticker).first()
        if company is None:
            company = Company(ticker=ticker, name="Pence Watch Co", exchange="LSE", currency=currency,
                              company_type="listed", valuation_model="dcf")
            db.add(company)
            db.flush()
        db.query(MarketPrice).filter(MarketPrice.company_id == company.id).delete()
        today = date.today()
        for i in range(0, 30):
            db.add(MarketPrice(company_id=company.id, date=today - timedelta(days=i), open=close,
                               high=close, low=close, close=close, adj_close=None, quote_currency=quote))
        if db.query(ThesisVersion).filter(ThesisVersion.company_id == company.id).first() is None:
            db.add(ThesisVersion(
                tenant_id=tenant.id if tenant else 1, company_id=company.id, version=1,
                status="published", thesis_markdown="t", executive_summary="s", expected_value=fair,
            ))
        if db.query(FundamentalModelVersion).filter(FundamentalModelVersion.company_id == company.id).first() is None:
            db.add(FundamentalModelVersion(
                tenant_id=tenant.id if tenant else 1, company_id=company.id, version=1,
                engine_version="test", algorithm_version="test", framework_key="dcf", horizon_years=10,
                status="ok", publishable=True, input_fingerprint="input", forecast_fingerprint="forecast",
                market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
            ))
        db.commit()
    finally:
        db.close()


def _side(monkeypatch, ticker: str):
    async def no_earnings(desde, hasta, client=None):
        return {"status": "ok", "events": [], "errors": []}

    monkeypatch.setattr("app.api.routes.watchlist.fetch_earnings_range", no_earnings)
    res = TestClient(main.app).get("/api/watchlist/monitor", params={"tickers": ticker})
    assert res.status_code == 200
    row = res.json()["items"][ticker]
    return row["valuation_side"]


def test_london_close_in_pence_below_fair_value_is_undervalued(monkeypatch):
    # 26,50 £ (2.650 peniques) frente a un valor justo de 30 £.
    _seed("PNCW.L", 2650.0, "GBp", "GBP", 30.0)
    assert _side(monkeypatch, "PNCW.L") == "infravalorada"


def test_london_close_in_pence_above_fair_value_is_overvalued(monkeypatch):
    _seed("PNCX.L", 3200.0, "GBp", "GBP", 30.0)
    assert _side(monkeypatch, "PNCX.L") == "sobrevalorada"


def test_ficha_en_gbx_compara_en_libras(monkeypatch):
    # Ficha creada solo con el ticker: divisa «GBX» (sufijo .L). El cierre en
    # peniques quedaba en peniques (misma unidad que la ficha) frente a 30 £.
    _seed("PNCZ.L", 2650.0, "GBp", "GBX", 30.0)
    assert _side(monkeypatch, "PNCZ.L") == "infravalorada"
