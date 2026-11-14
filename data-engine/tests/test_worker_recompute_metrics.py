"""Actor recompute_fundamental_metrics y su encadenado por chunks.

Contratos fijados:
- el chunk siguiente NO pasa por la admision acotada de la cola KPI: si el
  send inmediato lanza QueueCapacityError se reenvia con delay (mismo
  cursor y limite), nunca se pierde el barrido;
- solo se encadena cuando el chunk sale lleno (len == limit) y NO hay
  ticker concreto: un barrido de una empresa nunca se auto-encola;
- una empresa que falla no frena el barrido: rollback, error anotado y
  status partial;
- un fallo de sesion pasa por _handle_actor_error (payload estructurado).

Run from data-engine/:
    pytest tests/test_worker_recompute_metrics.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.workers import dramatiq_app as worker
from app.workers.bounded_broker import QueueCapacityError


@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(
        db=MagicMock(),
        rolled=[],
        handled=[],
        chained=[],
        session_error=None,
    )
    e.db.info = {"tenant_id": 1}

    def session(tenant, user):
        if e.session_error:
            raise e.session_error
        return e.db

    def handle(actor, exc, **ctx):
        e.handled.append((actor, exc, ctx))
        return {"status": "error", "actor": actor, "error": {"type": type(exc).__name__}}

    monkeypatch.setattr(worker, "_session", session)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))
    monkeypatch.setattr(worker, "_handle_actor_error", handle)
    monkeypatch.setattr(worker, "_send_next_recompute_chunk", lambda *a: e.chained.append(a))
    return e


def _patch_services(monkeypatch, calculate):
    """MetricCalculationService y market cap derivado, sin hechos reales."""
    class Service:
        def calculate_all(self, db, company, persist):
            return calculate(company)

    monkeypatch.setattr("app.services.metric_calculation_service.MetricCalculationService", Service)
    monkeypatch.setattr(
        "app.services.derived_market_cap_service.refresh_derived_market_cap",
        lambda db, company, ttl=None: {"status": "ok"},
    )


def _companies(env, tickers):
    env.db.scalars.return_value.all.return_value = [SimpleNamespace(ticker=t) for t in tickers]


# --- _send_next_recompute_chunk ---------------------------------------------


def test_send_next_chunk_inmediato_sin_delay(monkeypatch):
    sent, delayed = [], []
    monkeypatch.setattr(worker.recompute_fundamental_metrics, "send", lambda *a, **kw: sent.append((a, kw)))
    monkeypatch.setattr(
        worker.recompute_fundamental_metrics, "send_with_options",
        lambda *a, **kw: delayed.append((a, kw)),
    )

    worker._send_next_recompute_chunk(1, "u", "AAA", 50)

    assert sent == [((1, "u"), {"start_from": "AAA", "limit": 50})]
    assert delayed == []


def test_send_next_chunk_cola_llena_difiere_mismo_cursor(monkeypatch):
    delayed = []

    def full(*a, **kw):
        raise QueueCapacityError("kpis llena")

    monkeypatch.setattr(worker.recompute_fundamental_metrics, "send", full)
    monkeypatch.setattr(
        worker.recompute_fundamental_metrics, "send_with_options",
        lambda *a, **kw: delayed.append((a, kw)),
    )

    worker._send_next_recompute_chunk(1, "u", "AAA", 50)

    assert delayed == [(
        (),
        {"args": (1, "u"), "kwargs": {"start_from": "AAA", "limit": 50},
         "delay": worker.RECOMPUTE_CHAIN_DELAY_MS},
    )]


# --- actor -------------------------------------------------------------------


def test_chunk_parcial_no_encadena(env, monkeypatch):
    _companies(env, ["AAA"])
    _patch_services(monkeypatch, lambda company: [SimpleNamespace(status="ok")])

    out = worker.recompute_fundamental_metrics.fn(tenant_id=1, user_id="u", limit=5)

    assert out["status"] == "ok"
    assert out["companies_processed"] == 1
    assert out["metric_statuses"] == {"ok": 1}
    assert out["next_start_from"] is None
    assert env.chained == []
    env.db.close.assert_called_once_with()


def test_chunk_lleno_encadena_desde_el_ultimo_ticker(env, monkeypatch):
    _companies(env, ["AAA", "BBB"])
    _patch_services(monkeypatch, lambda company: [SimpleNamespace(status="ok")])

    out = worker.recompute_fundamental_metrics.fn(tenant_id=1, user_id="u", limit=2)

    assert out["next_start_from"] == "BBB"
    assert env.chained == [(1, "u", "BBB", 2)]


def test_ticker_concreto_nunca_encadena(env, monkeypatch):
    _companies(env, ["AAA", "AAB"])
    _patch_services(monkeypatch, lambda company: [SimpleNamespace(status="ok")])

    out = worker.recompute_fundamental_metrics.fn(tenant_id=1, user_id="u", ticker="aaa", limit=2)

    assert out["next_start_from"] is None
    assert env.chained == []


def test_empresa_que_falla_no_frena_el_barrido(env, monkeypatch):
    _companies(env, ["AAA", "BBB"])
    boom = KeyError("hechos incoherentes")

    def calculate(company):
        if company.ticker == "AAA":
            raise boom
        return [SimpleNamespace(status="ok"), SimpleNamespace(status="unavailable")]

    _patch_services(monkeypatch, calculate)

    out = worker.recompute_fundamental_metrics.fn(tenant_id=1, user_id="u", limit=5)

    assert out["status"] == "partial"
    assert out["companies_processed"] == 1
    assert out["metric_statuses"] == {"ok": 1, "unavailable": 1}
    assert out["errors"] == [{"ticker": "AAA", "type": "KeyError", "message": str(boom)[:200]}]
    assert env.rolled == [env.db]
    env.db.close.assert_called_once_with()


def test_todas_fallan_status_error(env, monkeypatch):
    _companies(env, ["AAA"])

    def calculate(company):
        raise ValueError("sin periodos")

    _patch_services(monkeypatch, calculate)

    out = worker.recompute_fundamental_metrics.fn(tenant_id=1, user_id="u", limit=5)

    assert out["status"] == "error"
    assert out["companies_processed"] == 0


def test_error_de_sesion_es_estructurado(env):
    env.session_error = ValueError("tenant_id and user_id are required for background jobs")

    out = worker.recompute_fundamental_metrics.fn(tenant_id=None, user_id=None)

    assert out["status"] == "error"
    assert env.handled and isinstance(env.handled[0][1], ValueError)
