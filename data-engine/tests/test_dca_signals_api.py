"""API de senales DCA: listado, ajuste del minimo por ticker y evaluacion manual."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

import main
from app.api.routes import watchlist as watchlist_routes
from app.core.database import SessionLocal, init_db
from app.models import DcaAlertOverride, DcaSignalState, ResearchAlert, WatchItem
from app.services import dca_signal_service
from app.services.dca_signal_service import FetchedHistory, PriceRow

SYMBOLS = ["DCATST", "DCAOFF"]


def _cleanup() -> None:
    with SessionLocal() as db:
        db.execute(delete(WatchItem).where(WatchItem.symbol.in_(SYMBOLS)))
        db.execute(delete(DcaSignalState).where(DcaSignalState.symbol.in_(SYMBOLS)))
        db.execute(delete(DcaAlertOverride).where(DcaAlertOverride.symbol.in_(SYMBOLS)))
        db.execute(delete(ResearchAlert).where(ResearchAlert.alert_type == "dca_level"))
        db.commit()


@pytest.fixture
def client(monkeypatch):
    init_db()
    _cleanup()
    watchlist_routes._dca_last_manual_run.clear()
    today = date.today()
    rows: list[PriceRow] = []
    y, m = today.year, today.month
    months = []
    for _ in range(30):
        months.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    for y, m in months[:-1]:
        rows.append(PriceRow(day=date(y, m, 1), close=100.0))
    rows.append(PriceRow(day=date(months[-1][0], months[-1][1], 1), close=55.0))

    def fake_fetch(symbol: str) -> FetchedHistory:
        return FetchedHistory(rows=rows, currency="USD")

    monkeypatch.setattr(dca_signal_service, "fetch_yahoo_history", fake_fetch)
    yield TestClient(main.app)
    _cleanup()


def test_list_without_evaluation_shows_tracked_symbols(client):
    assert client.post("/api/watchlist", json={"symbol": "dcatst"}).status_code == 201
    response = client.get("/api/watchlist/dca-signals")
    assert response.status_code == 200
    body = response.json()
    assert body["global_min_level"] == 2
    assert [z["level"] for z in body["zones"]] == [4, 3, 2, 1, -1, -2]
    item = next(i for i in body["items"] if i["symbol"] == "DCATST")
    assert item["in_watchlist"] is True and item["in_portfolio"] is False
    assert item["state"] is None
    assert item["effective_min_level"] == 2 and item["min_level_override"] is None


def test_set_min_level_override_and_reset(client):
    client.post("/api/watchlist", json={"symbol": "DCAOFF"})
    response = client.put("/api/watchlist/dcaoff/dca-alert-min-level", json={"min_level": 0})
    assert response.status_code == 200
    assert response.json() == {"symbol": "DCAOFF", "min_level_override": 0, "effective_min_level": 0}
    item = next(i for i in client.get("/api/watchlist/dca-signals").json()["items"] if i["symbol"] == "DCAOFF")
    assert item["alerts_on"] is False
    response = client.put("/api/watchlist/DCAOFF/dca-alert-min-level", json={"min_level": None})
    assert response.json()["effective_min_level"] == 2
    assert client.put("/api/watchlist/DCAOFF/dca-alert-min-level", json={"min_level": 5}).status_code == 422
    assert client.put("/api/watchlist/NOPE123/dca-alert-min-level", json={"min_level": 3}).status_code == 404


def test_manual_evaluate_persists_state_and_is_rate_limited(client):
    client.post("/api/watchlist", json={"symbol": "DCATST"})
    response = client.post("/api/watchlist/dca-signals/evaluate")
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["evaluated"] >= 1
    item = next(i for i in client.get("/api/watchlist/dca-signals").json()["items"] if i["symbol"] == "DCATST")
    state = item["state"]
    assert state is not None
    assert state["close"] == 55.0 and state["currency"] == "USD"
    assert state["status"] in {"forming", "confirmed"}
    assert set(state["level_prices"]) == {"2x", "3x", "4x"}
    again = client.post("/api/watchlist/dca-signals/evaluate")
    assert again.status_code == 429
    assert "Retry-After" in again.headers


def test_hit_rates_endpoint(client):
    client.post("/api/watchlist", json={"symbol": "DCATST"})
    # Sin evaluar: 404 explicito, no una tabla vacia inventada.
    assert client.get("/api/watchlist/dca-signals/DCATST/hit-rates").status_code == 404
    assert client.post("/api/watchlist/dca-signals/evaluate").status_code == 200
    response = client.get("/api/watchlist/dca-signals/dcatst/hit-rates")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["symbol"] == "DCATST" and body["available"] is True
    assert body["horizons"] == [3, 6, 12, 24, 36]
    assert [row["key"] for row in body["rows"]] == ["2x-4x", "4x", "3x", "2x"]
    assert all(row["color"] for row in body["rows"])
    assert body["disclaimer"].startswith("Histórico, hipotético")
