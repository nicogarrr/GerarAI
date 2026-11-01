"""Valoraciones y precios ProPicks: trabajo por tandas con presupuesto, sin dead-letter.

Lectura de dead-letter en prod (1-nov-2026): 5 refresh_valuation_metrics y
1 refresh_propicks_prices murieron por TimeLimitExceeded. Ambos recorrian su
universo entero en una sola corrida; al matarla el TimeLimit, el reintento
(max_retries=1) volvia a empezar y acababa en la cola XQ.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from types import SimpleNamespace

import dramatiq
import pytest

from app.workers import dramatiq_app


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class _Redis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key):
        self.store.pop(key, None)

    def eval(self, script, numkeys, key, token):
        if self.store.get(key) == token:
            self.store.pop(key)
            return 1
        return 0


def _last_attempt(monkeypatch, actor_name):
    message = SimpleNamespace(
        options={"retries": 1, "max_retries": 1}, actor_name=actor_name, message_timestamp=time.time() * 1000
    )
    monkeypatch.setattr(dramatiq_app.CurrentMessage, "get_current_message", classmethod(lambda cls: message))


# ---------- valoraciones ----------


def test_compute_corta_por_presupuesto_con_cursor_y_lo_hecho_guardado():
    from app.services.ticker_news_lane import Deadline
    from app.services.valuation_metrics_service import (
        ValuationTimeBudgetExhausted,
        compute_valuation_metrics,
    )
    from tests.test_propicks_prices import _db
    from tests.test_valuation_metrics import _seed_pb

    db = _db()
    companies = [_seed_pb(db, "AAA"), _seed_pb(db, "BBB")]
    clock = _Clock()
    deadline = Deadline(10, clock=clock)
    vistos = []

    def dividends(symbol):
        vistos.append(symbol)
        clock.now += 11  # la primera empresa gasta el presupuesto
        return []

    with pytest.raises(ValuationTimeBudgetExhausted) as caught:
        compute_valuation_metrics(
            db,
            companies,
            as_of=date(2026, 10, 27),
            dividend_fetcher=dividends,
            finnhub_yield_fetcher=lambda t: None,
            commit_per_company=True,
            deadline=deadline,
        )
    assert len(vistos) == 1
    assert caught.value.last_completed_ticker == "AAA"


def _actor_env(monkeypatch, refresh):
    fake = _Redis()
    monkeypatch.setattr("app.services.connectors.finnhub.finnhub_blocked_for", lambda: 0.0)
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: fake)
    monkeypatch.setattr(dramatiq_app, "_session", lambda *a, **k: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda *a, **k: "token")
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda *a, **k: None)
    monkeypatch.setattr(dramatiq_app, "_rollback", lambda db: None)
    monkeypatch.setattr("app.services.valuation_metrics_service.refresh_valuation_metrics", refresh)
    sent = []
    monkeypatch.setattr(
        dramatiq_app.refresh_valuation_metrics, "send_with_options", lambda **k: sent.append(k)
    )
    return fake, sent


def test_actor_presupuesto_agotado_guarda_cursor_y_sigue_en_otro_mensaje(monkeypatch):
    from app.services.valuation_metrics_service import ValuationTimeBudgetExhausted

    def _refresh(db, *, start_after_ticker=None, deadline=None, **kwargs):
        assert deadline is not None  # el actor siempre pasa presupuesto
        raise ValuationTimeBudgetExhausted("MMM")

    fake, sent = _actor_env(monkeypatch, _refresh)
    result = dramatiq_app.refresh_valuation_metrics.fn(tenant_id=1, user_id="u")
    assert result["status"] == "partial"
    assert result["reason"] == "time_budget"
    assert fake.store.get("valuation_metrics:cursor:1") == "MMM"
    assert len(sent) == 1
    assert sent[0]["kwargs"] == {"tenant_id": 1, "user_id": "u"}
    assert sent[0]["delay"] >= 60_000


def test_actor_429_en_el_ultimo_intento_guarda_cursor_y_no_va_a_dead_letter(monkeypatch):
    from app.services.valuation_metrics_service import ValuationUniverseRateSuspended

    def _refresh(db, *, start_after_ticker=None, **kwargs):
        raise ValuationUniverseRateSuspended("KKK", 42.0)

    fake, _ = _actor_env(monkeypatch, _refresh)
    _last_attempt(monkeypatch, "refresh_valuation_metrics")
    result = dramatiq_app.refresh_valuation_metrics.fn(tenant_id=1, user_id="u")
    assert result["status"] == "skipped"
    assert result["reason"] == "rate_limited_retries_exhausted"
    assert fake.store.get("valuation_metrics:cursor:1") == "KKK"


def test_actor_cooldown_finnhub_en_el_ultimo_intento_no_va_a_dead_letter(monkeypatch):
    monkeypatch.setattr("app.services.connectors.finnhub.finnhub_blocked_for", lambda: 30.0)
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: None)
    _last_attempt(monkeypatch, "refresh_valuation_metrics")
    result = dramatiq_app.refresh_valuation_metrics.fn(tenant_id=1, user_id="u")
    assert result["status"] == "skipped"
    assert result["reason"] == "rate_limited_retries_exhausted"


def test_actor_cooldown_finnhub_con_presupuesto_sigue_reencolando(monkeypatch):
    monkeypatch.setattr("app.services.connectors.finnhub.finnhub_blocked_for", lambda: 30.0)
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: None)
    with pytest.raises(dramatiq.Retry):
        dramatiq_app.refresh_valuation_metrics.fn(tenant_id=1, user_id="u")


# ---------- precios ProPicks ----------


def _propicks_run(db, tickers):
    from app.models import ProPickCandidate, ProPickRun
    from tests.test_propicks_prices import _company

    run = ProPickRun(
        as_of=datetime.now(UTC),
        status="completed",
        funnel_version="test",
        universe_size=len(tickers),
        passed_count=len(tickers),
        top_n=5,
        duration_ms=1,
        params={},
    )
    db.add(run)
    companies = [_company(t) for t in tickers]
    db.add_all(companies)
    db.flush()
    db.add_all(
        ProPickCandidate(
            run_id=run.id,
            company_id=c.id,
            passed=True,
            rank=i + 1,
            score=90.0 - i,
            failed_gates=[],
            metrics={},
            coverage={},
        )
        for i, c in enumerate(companies)
    )
    db.commit()
    return companies


def test_precios_propicks_se_piden_por_tandas(monkeypatch):
    from app.services import propicks_price_service as svc
    from tests.test_propicks_prices import _db, _fake_fetcher

    monkeypatch.setattr(svc, "PROPICKS_PRICE_CHUNK", 2)
    llamadas = []

    def fetcher(symbols, *, period="1y"):
        llamadas.append(list(symbols))
        return _fake_fetcher(symbols, period=period)

    with _db() as db:
        _propicks_run(db, ["AAA", "BBB", "CCC"])
        result = svc.refresh_propicks_prices(db, fetcher=fetcher, as_of=date(2026, 9, 25))
    assert [len(c) for c in llamadas] == [2, 1]
    assert result["status"] == "ok"
    assert result["covered"] == 3


def test_precios_propicks_cortan_por_presupuesto_con_lo_hecho_guardado(monkeypatch):
    from sqlalchemy import func, select

    from app.models import MarketPrice
    from app.services import propicks_price_service as svc
    from tests.test_propicks_prices import _db, _fake_fetcher

    monkeypatch.setattr(svc, "PROPICKS_PRICE_CHUNK", 1)
    clock = _Clock()

    def fetcher(symbols, *, period="1y"):
        clock.now += 100
        return _fake_fetcher(symbols, period=period)

    with _db() as db:
        _propicks_run(db, ["AAA", "BBB", "CCC"])
        result = svc.refresh_propicks_prices(
            db, fetcher=fetcher, as_of=date(2026, 9, 25), budget_seconds=150, clock=clock
        )
        assert result["status"] == "partial"
        assert result["truncated"] is True
        assert result["covered"] == 2
        db.rollback()  # lo escrito ya estaba confirmado por tanda
        assert db.scalar(select(func.count()).select_from(MarketPrice)) == 2 * 401


def test_actor_propicks_declara_limite_y_pasa_presupuesto(monkeypatch):
    seen = {}

    def _refresh(db, **kwargs):
        seen.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr("app.services.propicks_price_service.refresh_propicks_prices", _refresh)
    monkeypatch.setattr(dramatiq_app, "_session", lambda *a, **k: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda *a, **k: "token")
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda *a, **k: None)
    dramatiq_app.refresh_propicks_prices.fn(tenant_id=1, user_id="u")
    limit = dramatiq_app.refresh_propicks_prices.options["time_limit"]
    assert seen["budget_seconds"] * 1000 < limit
    assert limit <= 30 * 60 * 1000
