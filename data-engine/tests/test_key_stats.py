"""Datos clave de la ficha (estilo Stock Analysis): rango 52 semanas, proximos
resultados, ex-dividendo y beta. Solo fuentes gratuitas ya presentes; nada
inventado (campo sin dato = None)."""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

import main
from app.core.database import SessionLocal, init_db
from app.models import Company, MarketPrice
from app.models.entities import EarningsDate
from app.services import key_stats_service as ks

TODAY = date(2026, 10, 31)


def _epoch(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp())


def test_range_from_closes_uses_last_year_only():
    rows = [
        (TODAY - timedelta(days=400), 1.0),  # fuera de las 52 semanas
        (TODAY - timedelta(days=300), 80.0),
        (TODAY - timedelta(days=10), 130.0),
        (TODAY, 100.0),
    ]
    rng = ks.range_from_closes(rows, TODAY)
    assert rng is not None
    assert (rng.low, rng.high) == (80.0, 130.0)
    assert rng.low_date == (TODAY - timedelta(days=300)).isoformat()
    assert rng.sessions == 3
    assert ks.range_from_closes([], TODAY) is None


def test_normalize_yahoo_info_keeps_only_real_values():
    info = {
        "beta": 1.234,
        "exDividendDate": _epoch(TODAY + timedelta(days=5)),
        "earningsTimestamp": _epoch(TODAY + timedelta(days=12)),
        "isEarningsDateEstimate": True,
        "fiftyTwoWeekLow": 90.5,
        "fiftyTwoWeekHigh": 150.25,
        "currency": "USD",
    }
    out = ks.normalize_yahoo_info(info, TODAY)
    assert out["beta"] == 1.23
    assert out["ex_dividend"] == (TODAY + timedelta(days=5)).isoformat()
    assert out["earnings"] == (TODAY + timedelta(days=12)).isoformat()
    assert out["earnings_confirmed"] is False
    assert (out["low_52w"], out["high_52w"]) == (90.5, 150.25)
    bad = ks.normalize_yahoo_info(
        {
            "beta": float("nan"),
            "exDividendDate": None,
            "earningsTimestamp": _epoch(TODAY - timedelta(days=3)),
            "fiftyTwoWeekLow": 0,
            "fiftyTwoWeekHigh": "x",
        },
        TODAY,
    )
    assert bad["beta"] is None and bad["ex_dividend"] is None
    assert bad["earnings"] is None, "una fecha de resultados pasada no es la proxima"
    assert bad["low_52w"] is None and bad["high_52w"] is None


def _seed(ticker: str) -> None:
    init_db()
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.ticker == ticker).first()
        if company is None:
            company = Company(
                ticker=ticker,
                name="Key Stats Co",
                exchange="NASDAQ",
                currency="USD",
                company_type="listed",
                valuation_model="dcf",
            )
            db.add(company)
            db.flush()
        today = date.today()
        db.query(MarketPrice).filter(MarketPrice.company_id == company.id).delete()
        for i in range(0, 364):
            day = today - timedelta(days=i)
            close = 50.0 if i == 100 else 200.0 if i == 20 else 100.0
            db.merge(
                MarketPrice(
                    company_id=company.id,
                    date=day,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    adj_close=None,
                )
            )
        db.query(EarningsDate).filter(EarningsDate.ticker == ticker).delete()
        db.add(
            EarningsDate(
                ticker=ticker,
                event_date=today + timedelta(days=9),
                confirmed=True,
                source="yahoo",
                source_label="Yahoo Finance (calendarEvents)",
            )
        )
        db.commit()
    finally:
        db.close()


def test_key_stats_route_prefers_own_data_and_marks_sources(monkeypatch):
    _seed("KSTEST")
    seen: list[str] = []

    def fake_info(symbol: str) -> dict:
        seen.append(symbol)
        return {
            "beta": 0.87,
            "exDividendDate": _epoch(date.today() - timedelta(days=20)),
            "fiftyTwoWeekLow": 1.0,
            "fiftyTwoWeekHigh": 999.0,
            "currency": "USD",
        }

    monkeypatch.setattr(ks, "_fetch_yahoo_info", fake_info)
    ks.key_stats_service.clear()
    res = TestClient(main.app).get("/api/companies/kstest/key-stats")
    assert res.status_code == 200
    body = res.json()
    assert seen == ["KSTEST"]
    rng = body["range_52w"]
    assert (rng["low"], rng["high"]) == (50.0, 200.0), "manda el historico propio, no el de Yahoo"
    assert rng["source"] == ks.DB_CLOSES_SOURCE
    assert body["next_earnings"]["date"] == (date.today() + timedelta(days=9)).isoformat()
    assert body["next_earnings"]["confirmed"] is True
    assert body["ex_dividend"] == {
        "date": (date.today() - timedelta(days=20)).isoformat(),
        "upcoming": False,
        "confirmed": None,
        "source": ks.YAHOO_SOURCE,
    }
    assert body["beta"] == {"value": 0.87, "source": ks.YAHOO_BETA_SOURCE}


def test_key_stats_route_survives_yahoo_failure(monkeypatch):
    def boom(symbol: str) -> dict:
        raise RuntimeError("yahoo caido")

    monkeypatch.setattr(ks, "_fetch_yahoo_info", boom)
    ks.key_stats_service.clear()
    res = TestClient(main.app).get("/api/companies/NOEXISTE-KS/key-stats")
    assert res.status_code == 200
    body = res.json()
    assert body["range_52w"] is None and body["beta"] is None and body["ex_dividend"] is None
    assert body["next_earnings"] is None
    assert body["note"]
