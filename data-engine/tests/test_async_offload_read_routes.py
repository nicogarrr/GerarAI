"""Rutas de lectura/ingesta: el trabajo sincrono no corre en el event loop.

Misma sonda que en test_async_offload_companies: un helper sync con un
event loop en su hilo va contra el hallazgo; sin loop, va por el pool.
"""

import asyncio
from types import SimpleNamespace

import main
from app.core.database import init_db
from app.schemas import ChatResponse
from tests.auth_helpers import csrf_client

client = csrf_client(main.app)


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


def test_chat_hard_deadline_cuts_a_worker_that_blocks_the_thread(monkeypatch, caplog):
    """Un paso que bloquea el hilo no puede alargar la respuesta mas alla del muro."""
    import time

    init_db()
    monkeypatch.setattr("app.api.routes.chat.CHAT_HARD_GRACE_SECONDS", 0.3)
    monkeypatch.setattr(
        "app.api.routes.chat.get_settings",
        lambda: SimpleNamespace(chat_total_timeout_seconds=0.4),
    )

    def blocking_answer(self, db, question, scope, ticker, enable_debate=False, page=None, history=None):  # noqa: ARG001
        async def _result():
            time.sleep(3)  # bloquea el hilo y su loop: ningun wait_for interno puede cortarlo
            return ChatResponse(answer="tarde", sources=[])

        return _result()

    monkeypatch.setattr("app.services.chat_service.ChatService.answer", blocking_answer)
    started = time.monotonic()
    with caplog.at_level("WARNING"):
        response = client.post("/api/chat", json={"question": "que es el wacc"})
    elapsed = time.monotonic() - started
    assert response.status_code == 200, response.text
    body = response.json()
    assert elapsed < 1.5, elapsed
    assert body["llm_trace"]["fallback_reason"] == "chat_hard_deadline"
    assert body["model"] == "deterministic"
    assert "worker thread stack" in caplog.text
    assert "time.sleep" in caplog.text or "_result" in caplog.text


def test_chat_stuck_workers_are_capped_and_released(monkeypatch):
    """Hilos abandonados por el muro siguen contando hasta que terminan."""
    import time

    import app.api.routes.chat as chat_route

    init_db()
    deadline = time.monotonic() + 6
    while chat_route._live_workers and time.monotonic() < deadline:
        time.sleep(0.1)  # hilos abandonados de otros tests
    assert chat_route._live_workers == 0
    monkeypatch.setattr(chat_route, "CHAT_HARD_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(chat_route, "CHAT_MAX_LIVE_WORKERS", 2)
    monkeypatch.setattr(
        chat_route, "get_settings", lambda: SimpleNamespace(chat_total_timeout_seconds=0.2)
    )

    def blocking_answer(self, db, question, scope, ticker, enable_debate=False, page=None, history=None):  # noqa: ARG001
        async def _result():
            time.sleep(2.5)
            return ChatResponse(answer="tarde", sources=[])

        return _result()

    monkeypatch.setattr("app.services.chat_service.ChatService.answer", blocking_answer)
    reasons = [
        client.post("/api/chat", json={"question": "que es el wacc"}).json()["llm_trace"]["fallback_reason"]
        for _ in range(3)
    ]
    assert reasons == ["chat_hard_deadline", "chat_hard_deadline", "chat_busy"]
    time.sleep(3)  # los hilos terminan y liberan su hueco
    assert chat_route._live_workers == 0


def test_chat_live_worker_cap_is_exact_under_a_burst(monkeypatch):
    """Rafaga concurrente real: nunca mas hilos vivos que el tope, y todos se liberan."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import app.api.routes.chat as chat_route

    init_db()
    deadline = time.monotonic() + 8
    while chat_route._live_workers and time.monotonic() < deadline:
        time.sleep(0.1)
    assert chat_route._live_workers == 0
    cap = 3
    monkeypatch.setattr(chat_route, "CHAT_HARD_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(chat_route, "CHAT_MAX_LIVE_WORKERS", cap)
    monkeypatch.setattr(
        chat_route, "get_settings", lambda: SimpleNamespace(chat_total_timeout_seconds=0.2)
    )
    running = 0
    peak = 0
    lock = threading.Lock()

    def blocking_answer(self, db, question, scope, ticker, enable_debate=False, page=None, history=None):  # noqa: ARG001
        async def _result():
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            try:
                time.sleep(2)
            finally:
                with lock:
                    running -= 1
            return ChatResponse(answer="tarde", sources=[])

        return _result()

    monkeypatch.setattr("app.services.chat_service.ChatService.answer", blocking_answer)

    def call(_):
        return client.post("/api/chat", json={"question": "que es el wacc"}).json()["llm_trace"]["fallback_reason"]

    with ThreadPoolExecutor(max_workers=20) as pool:
        reasons = list(pool.map(call, range(20)))
    assert peak <= cap, peak
    assert reasons.count("chat_hard_deadline") == cap, reasons
    assert reasons.count("chat_busy") == 20 - cap, reasons
    time.sleep(2.5)
    assert chat_route._live_workers == 0
