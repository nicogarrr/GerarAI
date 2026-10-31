"""API de senales DCA: listado, ajuste del minimo por ticker y evaluacion manual."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

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


class _RedisGate:
    """Contract double for endpoint tests; real Redis Lua is checked separately."""
    def __init__(self):
        self.data = {}
    def set(self, key, value, **kw):
        self.data[key] = value.encode() if isinstance(value, str) else value
    def get(self, key):
        return self.data.get(key)
    def delete(self, key):
        self.data.pop(key, None)
    def close(self):
        pass
    def eval(self, script, count, *args):
        if count == 2:
            lock, cooldown, token, *_ = args
            if lock in self.data: return -1
            if cooldown in self.data: return 300
            self.set(lock, token); self.set(cooldown, token)
            return 0
        lock, token, *_ = args
        if "EXPIRE" in script:  # renovacion de la reserva por el worker
            return 1 if self.get(lock) == token.encode() else 0
        if self.get(lock) == token.encode(): self.delete(lock)
        return 1


def run_manual_batch() -> dict:
    """Camino manual real sin broker: recibo como /evaluate-async y luego el job
    del worker (``run_manual_job``). Datos de test sin tenant (legacy)."""
    from datetime import UTC, datetime

    from app.models import DcaEvaluationRun
    from app.services import dca_manual, dca_manual_job

    with SessionLocal() as db:
        db.info["tenant_id"] = None
        gate = dca_manual_job.redis_client()
        token, wait = dca_manual.acquire_manual_gate(gate, "None")
        if token is None:
            return {"blocked": wait}
        pending = dca_manual.pending_symbols(db)
        requested = pending[:dca_manual.MAX_SYMBOLS]
        row = DcaEvaluationRun(trigger="manual", status="queued", started_at=datetime.now(UTC),
            detail={"requested_symbols": requested, "pending_remaining": max(0, len(pending) - len(requested))})
        db.add(row)
        db.commit()
        dca_manual_job.run_manual_job(db, row.id, token)
        db.refresh(row)
        return row.detail["summary"]


@pytest.fixture
def client(monkeypatch):
    init_db()
    _cleanup()
    import redis
    store = _RedisGate()
    monkeypatch.setattr(redis.Redis, 'from_url', lambda *a, **kw: store)
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
    # Ultimo cierre reciente: con la puerta de frescura una barra del dia 1 de
    # hace semanas ya no cuenta como senal actual.
    last_day = max(date(months[-1][0], months[-1][1], 1), today - timedelta(days=1))
    rows.append(PriceRow(day=last_day, close=55.0))

    def fake_fetch(symbol: str) -> FetchedHistory:
        return FetchedHistory(rows=rows, currency="USD")

    monkeypatch.setattr(dca_signal_service, "fetch_yahoo_history", fake_fetch)
    client = TestClient(main.app)
    # El middleware CSRF exige token en todo metodo mutante. Sin el, estos
    # tests solo pasaban tapados por el orden de la suite completa y fallaban
    # al ejecutar este archivo aislado.
    csrf = client.get("/api/csrf-token")
    assert csrf.status_code == 200, csrf.text
    client.headers["X-CSRF-Token"] = csrf.json()["csrf_token"]
    yield client
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
    summary = run_manual_batch()
    assert summary["evaluated"] >= 1
    item = next(i for i in client.get("/api/watchlist/dca-signals").json()["items"] if i["symbol"] == "DCATST")
    state = item["state"]
    assert state is not None
    assert state["close"] == 55.0 and state["currency"] == "USD"
    assert state["status"] in {"forming", "confirmed"}
    assert set(state["level_prices"]) == {"2x", "3x", "4x"}
    assert run_manual_batch() == {"blocked": 300}


def test_sync_evaluate_endpoint_is_retired(client):
    """La UI usa /evaluate-async; el POST sincrono viejo ya no existe."""
    assert client.post("/api/watchlist/dca-signals/evaluate").status_code in {404, 405}
    paths = set(main.app.openapi()["paths"])
    assert "/api/watchlist/dca-signals/evaluate" not in paths
    assert "/api/watchlist/dca-signals/evaluate-async" in paths


def test_hit_rates_endpoint(client):
    client.post("/api/watchlist", json={"symbol": "DCATST"})
    # Sin evaluar: 404 explicito, no una tabla vacia inventada.
    assert client.get("/api/watchlist/dca-signals/DCATST/hit-rates").status_code == 404
    run_manual_batch()
    response = client.get("/api/watchlist/dca-signals/dcatst/hit-rates")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["symbol"] == "DCATST" and body["available"] is True
    assert body["horizons"] == [3, 6, 12, 24, 36]
    assert [row["key"] for row in body["rows"]] == ["2x-4x", "4x", "3x", "2x"]
    assert all(row["color"] for row in body["rows"])
    assert body["disclaimer"].startswith("Histórico, hipotético")


def test_backtest_endpoint_any_ticker_plain_vs_levels(client):
    response = client.get("/api/watchlist/dca-signals/dcabt/backtest", params={"base": 50})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["symbol"] == "DCABT" and body["available"] is True
    plans = {p["key"]: p for p in body["plans"]}
    assert set(plans) == {"plain", "levels", "fixed_budget"}
    assert plans["plain"]["invested"] == 50 * body["months"]
    assert plans["fixed_budget"]["invested"] == plans["plain"]["invested"]
    assert body["params_version"] == "nico-v1"
    assert body["disclaimer"].startswith("Histórico, hipotético")
    assert client.get("/api/watchlist/dca-signals/DCABT/backtest", params={"start": "2026-13"}).status_code == 422


def test_backtest_uses_new_york_today_at_month_end(client, monkeypatch):
    """01:30 UTC del 1 de noviembre = 31 de octubre en NY: octubre sigue en curso."""
    from datetime import UTC, date, datetime

    from app.api.routes import watchlist as route
    from app.services import dca_backtest

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 1, 1, 30, tzinfo=UTC)

    seen: dict = {}
    real = dca_backtest.backtest_dca

    def spy(*args, **kwargs):
        seen["today"] = kwargs.get("today")
        return real(*args, **kwargs)

    monkeypatch.setattr(route, "datetime", _Clock)
    monkeypatch.setattr(dca_backtest, "backtest_dca", spy)
    response = client.get("/api/watchlist/dca-signals/DCABT/backtest")
    assert response.status_code == 200, response.text
    assert seen["today"] == date(2026, 10, 31)


def test_list_reports_when_daily_evaluation_is_disabled(client, monkeypatch):
    """Prueba real en vivo (realqa-15): con DCA_EVALUATION_ENABLED=false en el
    servidor el job diario sale «disabled» cada noche, ningun ticker tiene
    nivel y el panel decia «Sin evaluar» sin explicar por que. El listado
    declara ahora si la evaluacion diaria esta encendida."""
    from app.core.config import get_settings

    client.post("/api/watchlist", json={"symbol": "DCATST"})
    monkeypatch.setenv("DCA_EVALUATION_ENABLED", "false")
    get_settings.cache_clear()
    try:
        body = client.get("/api/watchlist/dca-signals").json()
        assert body["evaluation_enabled"] is False
        # «Evaluar ahora» sigue funcionando con la evaluacion diaria apagada.
        run_manual_batch()
        item = next(i for i in client.get("/api/watchlist/dca-signals").json()["items"] if i["symbol"] == "DCATST")
        assert item["state"] is not None
    finally:
        monkeypatch.delenv("DCA_EVALUATION_ENABLED")
        get_settings.cache_clear()
    assert client.get("/api/watchlist/dca-signals").json()["evaluation_enabled"] is True


def test_list_flags_stale_saved_level(client):
    """Un nivel guardado con el ultimo cierre viejo sale marcado como desactualizado."""
    client.post("/api/watchlist", json={"symbol": "DCATST"})
    run_manual_batch()
    fresh = next(i for i in client.get("/api/watchlist/dca-signals").json()["items"] if i["symbol"] == "DCATST")
    assert fresh["state"]["stale"] is False
    assert fresh["state"]["data_age_days"] is not None and fresh["state"]["data_age_days"] <= 14
    with SessionLocal() as db:
        state = db.scalar(select(DcaSignalState).where(DcaSignalState.symbol == "DCATST"))
        assert state is not None
        state.signal_date = date.today() - timedelta(days=40)
        db.commit()
    stale = next(i for i in client.get("/api/watchlist/dca-signals").json()["items"] if i["symbol"] == "DCATST")
    assert stale["state"]["stale"] is True
    assert stale["state"]["data_age_days"] >= 39
    assert stale["state"]["level"] == fresh["state"]["level"]  # el nivel se conserva, pero marcado


def test_staleness_helper_uses_configured_limit():
    today = date(2026, 10, 27)
    assert watchlist_routes._dca_staleness(None, today) == (None, False)
    assert watchlist_routes._dca_staleness(date(2026, 10, 13), today) == (14, False)
    assert watchlist_routes._dca_staleness(date(2026, 10, 12), today) == (15, True)


def _tenant_db():
    db = SessionLocal()
    db.info.update(tenant_id=987654, user_id="u-gate")
    return db


def test_manual_uses_shared_lease_and_fails_closed_on_redis_outage(client, monkeypatch):
    import redis
    from fastapi import HTTPException
    store = redis.Redis.from_url('redis://unused')
    store.set('cavaai:job-lease:evaluate_dca_signals:987654', 'scheduler')
    with _tenant_db() as db, pytest.raises(HTTPException) as busy:
        watchlist_routes.enqueue_manual_dca(db)
    assert busy.value.status_code == 409
    assert store.get('cavaai:job-lease:evaluate_dca_signals:987654') == b'scheduler'
    store.delete('cavaai:job-lease:evaluate_dca_signals:987654')
    store.set('cavaai:dca-manual-cooldown:987654', 'x')
    with _tenant_db() as db, pytest.raises(HTTPException) as cooling:
        watchlist_routes.enqueue_manual_dca(db)
    assert cooling.value.status_code == 429 and "Retry-After" in cooling.value.headers
    store.delete('cavaai:dca-manual-cooldown:987654')
    monkeypatch.setattr('app.services.dca_manual.acquire_manual_gate',
        lambda *a: (_ for _ in ()).throw(redis.ConnectionError('test')))
    with _tenant_db() as db, pytest.raises(HTTPException) as down:
        watchlist_routes.enqueue_manual_dca(db)
    assert down.value.status_code == 503


def test_manual_limits_batch_and_reports_remaining(client, monkeypatch):
    monkeypatch.setattr('app.services.dca_manual.pending_symbols', lambda db: [f'T{i}' for i in range(23)])
    seen = []
    def evaluate(db, *, symbols=None):
        seen.append(symbols)
        return {'tracked': 23, 'evaluated': len(symbols), 'alerted': [], 'skipped': [],
            'errors': [], 'alerts_enabled': False, 'params_version': 'test'}
    monkeypatch.setattr('app.services.dca_signal_service.evaluate_watchlist', evaluate)
    result = run_manual_batch()
    assert len(seen[0]) == result['requested'] == 10
    assert result['pending_remaining'] == 13
    assert result['cooldown_seconds'] == 300
