"""Rutas de lectura/ingesta: el trabajo sincrono no corre en el event loop.

Misma sonda que en test_async_offload_companies: un helper sync con un
event loop en su hilo va contra el hallazgo; sin loop, va por el pool.
"""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
from app.core.database import init_db
from app.schemas import ChatResponse

client = TestClient(main.app)


def _off_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return True
    return False


def test_chat_service_call_off_the_event_loop(monkeypatch):
    init_db()
    calls: list[bool] = []

    def fake_answer(self, db, question, scope, ticker, enable_debate=False, page=None, history=None):  # noqa: ARG001
        calls.append(_off_loop())

        async def _result():
            return ChatResponse(answer="a", sources=[])

        return _result()

    monkeypatch.setattr("app.services.chat_service.ChatService.answer", fake_answer)
    response = client.post("/api/chat", json={"question": "que es el wacc"})
    assert response.status_code == 200, response.text
    assert calls and all(calls)


def test_catalysts_held_tickers_off_the_event_loop(monkeypatch):
    init_db()
    calls: list[bool] = []

    def fake_held(db):  # noqa: ARG001
        calls.append(_off_loop())
        return [], []

    monkeypatch.setattr(
        "app.services.catalyst_calendar_service.held_tickers", fake_held
    )
    response = client.get("/api/calendar/catalysts")
    assert response.status_code == 200, response.text
    assert response.json()["held_count"] == 0
    assert calls and all(calls)


def test_sync_portfolio_dividends_off_the_event_loop(monkeypatch):
    init_db()
    calls: list[bool] = []

    def fake_sync(self, db):  # noqa: ARG001
        calls.append(_off_loop())

        async def _result():
            return {"status": "ok", "ingested": 0}

        return _result()

    monkeypatch.setattr(
        "app.services.dividend_ingestion_service.DividendIngestionService.sync_portfolio",
        fake_sync,
    )
    response = client.post("/api/portfolio/dividends/sync")
    assert response.status_code == 200, response.text
    assert calls and all(calls)


def test_sync_portfolio_splits_off_the_event_loop(monkeypatch):
    init_db()
    calls: list[bool] = []

    def fake_sync(self, db):  # noqa: ARG001
        calls.append(_off_loop())

        async def _result():
            return {"status": "ok", "ingested": 0}

        return _result()

    monkeypatch.setattr(
        "app.services.split_ingestion_service.SplitIngestionService.sync_portfolio",
        fake_sync,
    )
    response = client.post("/api/corporate-actions/splits/sync")
    assert response.status_code == 200, response.text
    assert calls and all(calls)


def test_company_events_off_the_event_loop(monkeypatch):
    init_db()
    calls: list[bool] = []

    def fake_resolve(db, ticker):  # noqa: ARG001
        calls.append(_off_loop())
        return SimpleNamespace(id=1, ticker=ticker)

    def fake_events(self, company):  # noqa: ARG001
        async def _result():
            return {
                "ticker": company.ticker,
                "company_name": company.ticker,
                "as_of": "2026-10-18",
                "calendar_status": "ok",
                "eps_history_status": "ok",
                "next_event": None,
                "history": [],
                "source": "test",
                "note": None,
            }

        return _result()

    monkeypatch.setattr("app.api.routes.company_events.resolve_company", fake_resolve)
    monkeypatch.setattr(
        "app.services.company_events_service.CompanyEventsService.get_events",
        fake_events,
    )
    response = client.get("/api/companies/PROBE/events")
    assert response.status_code == 200, response.text
    assert calls and all(calls)


def test_shorts_refresh_off_the_event_loop(monkeypatch):
    init_db()
    calls: list[bool] = []
    monkeypatch.setattr(
        "app.api.routes.data_health._company",
        lambda db, ticker: SimpleNamespace(id=1, ticker=ticker),  # noqa: ARG005
    )

    def fake_refresh(db, company):  # noqa: ARG001
        calls.append(_off_loop())

        async def _result():
            return {"status": "ok"}

        return _result()

    monkeypatch.setattr("app.api.routes.data_health.refresh_shorts", fake_refresh)
    response = client.post("/api/data-health/shorts/PROBE/refresh")
    assert response.status_code == 200, response.text
    assert calls and all(calls)


def test_import_ibkr_owner_check_off_the_event_loop(monkeypatch):
    init_db()
    calls: list[bool] = []

    def fake_owner(db):  # noqa: ARG001
        calls.append(_off_loop())
        return SimpleNamespace(ibkr_flex_account_id="U123")

    monkeypatch.setattr("app.api.routes.portfolio._require_ibkr_owner", fake_owner)
    monkeypatch.setattr(
        "app.services.connectors.ibkr.IBKRFlexClient.configured",
        lambda self: False,  # noqa: ARG005
    )
    response = client.post("/api/portfolio/import/ibkr")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "not_configured"
    assert calls and all(calls)
