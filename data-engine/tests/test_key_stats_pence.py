"""Rango de 52 semanas de la ficha en valores de Londres (peniques).

Los cierres de SHEL.L/TSCO.L se guardan en peniques (``quote_currency``
«GBp») y Yahoo declara la cotizacion en «GBp». El rango se devolvia con la
divisa en mayusculas («GBP») y los importes en peniques: la ficha pintaba
«2.400,00 £ – 2.900,00 £» para un valor que cotiza a 24-29 libras (x100).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import main
from app.core.database import SessionLocal, init_db
from app.models import Company, MarketPrice
from app.services import key_stats_service as ks


def _seed(ticker: str, currency: str, quote_currency: str | None) -> None:
    init_db()
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.ticker == ticker).first()
        if company is None:
            company = Company(
                ticker=ticker, name="Pence Co", exchange="LSE", currency=currency,
                company_type="listed", valuation_model="dcf",
            )
            db.add(company)
            db.flush()
        company.currency = currency
        today = datetime.now(UTC).date()
        db.query(MarketPrice).filter(MarketPrice.company_id == company.id).delete()
        for i in range(0, 300):
            close = 2400.0 if i == 100 else 2900.0 if i == 20 else 2650.0
            db.add(MarketPrice(
                company_id=company.id, date=today - timedelta(days=i), open=close, high=close,
                low=close, close=close, adj_close=None, quote_currency=quote_currency,
            ))
        db.commit()
    finally:
        db.close()


def _get(monkeypatch, ticker: str, info: dict | None = None) -> dict:
    def fake_info(symbol: str) -> dict:
        return dict(info or {})

    monkeypatch.setattr(ks, "_fetch_yahoo_info", fake_info)
    ks.key_stats_service.clear()
    res = TestClient(main.app).get(f"/api/companies/{ticker}/key-stats")
    assert res.status_code == 200
    return res.json()


def _money(body: dict) -> tuple[float, float, str]:
    rng = body["range_52w"]
    return rng["low"], rng["high"], body["currency"]


def test_own_closes_in_pence_with_company_in_pounds(monkeypatch):
    _seed("PNCA.L", "GBP", "GBp")
    low, high, ccy = _money(_get(monkeypatch, "PNCA.L"))
    assert (low, high, ccy) == (24.0, 29.0, "GBP"), "peniques no son libras"


def test_own_closes_in_pence_with_company_declared_in_pence(monkeypatch):
    _seed("PNCB.L", "GBp", "GBp")
    low, high, ccy = _money(_get(monkeypatch, "PNCB.L"))
    assert (low, high, ccy) == (24.0, 29.0, "GBP")


def test_yahoo_range_in_pence_without_own_data(monkeypatch):
    body = _get(monkeypatch, "NOEXISTE-PNC.L", {
        "fiftyTwoWeekLow": 2400.0, "fiftyTwoWeekHigh": 2900.0, "currency": "GBp",
    })
    low, high, ccy = _money(body)
    assert (low, high, ccy) == (24.0, 29.0, "GBP")
    assert body["range_52w"]["source"] == ks.YAHOO_RANGE_SOURCE


def test_us_listing_unchanged(monkeypatch):
    body = _get(monkeypatch, "NOEXISTE-PNC", {
        "fiftyTwoWeekLow": 10.0, "fiftyTwoWeekHigh": 20.0, "currency": "usd",
    })
    assert _money(body) == (10.0, 20.0, "USD")
