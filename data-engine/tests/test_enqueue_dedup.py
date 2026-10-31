"""Dedup de encolado "una copia en vuelo" + obsolescencia de mensajes viejos.

El worker de default (1 hilo) no drena los re-encolados periodicos del
scheduler (backlog del 28-oct-2026): coalesced_send frena el crecimiento en
origen y la guarda de obsolescencia drena el backlog sin ejecutar trabajo ya
superado. Invariantes:

1. Primer encolado de una clave: envia y deja marca; segundo: se suprime.
2. La marca muere al CONSUMIR el mensaje (el actor la borra al entrar).
3. Un mensaje mas viejo que su umbral se salta (stale_message) sin trabajar.
4. Reintentos (retries) y diferidos (eta) NUNCA se consideran obsoletos.
5. stale_after_seconds=None desactiva la obsolescencia (syncs IBKR, diarios).
6. Redis caido es fail-open: encola y ejecuta siempre.
7. Actores sin politica registrada se envian siempre.
"""

from __future__ import annotations

import inspect
import threading
import time
from types import SimpleNamespace

import pytest

from app.workers import dramatiq_app
from app.workers.dramatiq_app import _coalesce_on_success, coalesced_send


class FakeRedis:
    """Mini-Redis thread-safe con SET NX, INCR y compare-and-delete."""

    def __init__(self, raises=False):
        self.store = {}
        self.raises = raises
        self.lock = threading.Lock()

    def set(self, key, value, nx=False, ex=None):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            if nx and key in self.store:
                return None
            self.store[key] = value
            return True

    def get(self, key):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            value = self.store.get(key)
        return value.encode() if isinstance(value, str) else value

    def delete(self, key):
        with self.lock:
            self.store.pop(key, None)

    def exists(self, key):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            return int(key in self.store)

    def incr(self, key):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            self.store[key] = int(self.store.get(key, 0)) + 1
            return self.store[key]

    def expire(self, key, seconds):
        if self.raises:
            raise ConnectionError("redis caido")
        return True

    def eval(self, script, numkeys, *args):
        if self.raises:
            raise ConnectionError("redis caido")
        key, token = args
        with self.lock:
            if self.store.get(key) == token:
                self.store.pop(key)
                return 1
            return 0


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: client)


def _fake_actor(name="job"):
    sent = []

    def send(*args, **kwargs):
        sent.append((args, kwargs))
        return SimpleNamespace(message_id=f"msg-{len(sent)}")

    return SimpleNamespace(actor_name=name, send=send), sent


def _register_policy(monkeypatch, name, fn, window=60, key_parts=(), stale=60):
    monkeypatch.setitem(
        dramatiq_app._COALESCE_POLICIES,
        name,
        {"window": window, "key_parts": key_parts, "stale_after": stale, "sig": inspect.signature(fn)},
    )


def test_first_send_enqueues_and_marks_second_is_suppressed(monkeypatch):
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    actor, sent = _fake_actor()
    _register_policy(monkeypatch, "job", lambda tenant_id=None: None)

    assert coalesced_send(actor, 7) is not None
    assert coalesced_send(actor, 7) is None  # copia en vuelo: tick suprimido
    assert len(sent) == 1
    assert any(k.startswith("coalesce-enq:job") for k in client.store)


def test_mark_dies_when_the_actor_consumes_the_message(monkeypatch):
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    actor, sent = _fake_actor()
    executed = []

    @_coalesce_on_success("job", 60)
    def job():
        executed.append(1)
        return {"status": "ok"}

    _register_policy(monkeypatch, "job", lambda: None, stale=None)
    assert coalesced_send(actor) is not None
    assert coalesced_send(actor) is None
    job()  # el worker consume la copia pendiente: la marca muere al entrar
    assert executed == [1]
    assert coalesced_send(actor) is not None  # el siguiente tick ya encola
    assert len(sent) == 2


def test_send_failure_releases_the_mark(monkeypatch):
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    actor, _ = _fake_actor()

    def boom(*args, **kwargs):
        raise RuntimeError("broker caido")

    actor.send = boom
    _register_policy(monkeypatch, "job", lambda: None)
    with pytest.raises(RuntimeError):
        coalesced_send(actor)
    assert not any(k.startswith("coalesce-enq:") for k in client.store)


def test_actor_without_policy_always_sends(monkeypatch):
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    actor, sent = _fake_actor("sin_politica")
    assert coalesced_send(actor, 1) is not None
    assert coalesced_send(actor, 1) is not None
    assert len(sent) == 2


def test_redis_down_send_is_fail_open(monkeypatch):
    _patch_client(monkeypatch, FakeRedis(raises=True))
    actor, sent = _fake_actor()
    _register_policy(monkeypatch, "job", lambda: None)
    assert coalesced_send(actor) is not None
    assert coalesced_send(actor) is not None
    assert len(sent) == 2


def _patch_message(monkeypatch, message):
    monkeypatch.setattr(
        dramatiq_app.CurrentMessage,
        "get_current_message",
        classmethod(lambda cls: message),
    )


def test_stale_message_is_skipped_without_work(monkeypatch):
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    executed = []

    @_coalesce_on_success("job", 60)
    def job():
        executed.append(1)
        return {"status": "ok"}

    old = SimpleNamespace(options={}, message_timestamp=(time.time() - 3600) * 1000)
    _patch_message(monkeypatch, old)
    result = job()
    assert result["status"] == "skipped"
    assert result["reason"] == "stale_message"
    assert executed == []


def test_fresh_message_runs(monkeypatch):
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    executed = []

    @_coalesce_on_success("job", 3600)
    def job():
        executed.append(1)
        return {"status": "ok"}

    fresh = SimpleNamespace(options={}, message_timestamp=time.time() * 1000)
    _patch_message(monkeypatch, fresh)
    assert job()["status"] == "ok"
    assert executed == [1]


def test_retries_and_delayed_messages_are_never_stale(monkeypatch):
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    executed = []

    @_coalesce_on_success("job", 60)
    def job():
        executed.append(1)
        return {"status": "ok"}

    old_ts = (time.time() - 3600) * 1000
    _patch_message(monkeypatch, SimpleNamespace(options={"retries": 2}, message_timestamp=old_ts))
    assert job()["status"] == "ok"
    client.delete("coalesce:job")  # simula expiracion del claim
    _patch_message(monkeypatch, SimpleNamespace(options={"eta": 123}, message_timestamp=old_ts))
    assert job()["status"] == "ok"
    assert executed == [1, 1]


def test_stale_after_none_always_runs(monkeypatch):
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    executed = []

    @_coalesce_on_success("job", 60, stale_after_seconds=None)
    def job():
        executed.append(1)
        return {"status": "ok"}

    old = SimpleNamespace(options={}, message_timestamp=(time.time() - 86400) * 1000)
    _patch_message(monkeypatch, old)
    assert job()["status"] == "ok"
    assert executed == [1]


def test_no_current_message_runs(monkeypatch):
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    executed = []

    @_coalesce_on_success("job", 60)
    def job():
        executed.append(1)
        return {"status": "ok"}

    _patch_message(monkeypatch, None)
    assert job()["status"] == "ok"
    assert executed == [1]


def test_registered_policies_cover_the_periodic_default_and_prices_actors():
    policies = dramatiq_app._COALESCE_POLICIES
    for name in (
        "refresh_bottlenecks",
        "refresh_market_pipeline",
        "refresh_portfolio_prices_intraday",
        "refresh_rss_feeds",
        "refresh_ir_pages",
        "refresh_ticker_news",
        "refresh_sec_filings",
        "scan_contradictions",
        "scan_insider_watchlist",
        "refresh_paper_trades",
        "backfill_document_kpis",
        "refresh_earnings_calendar",
    ):
        assert name in policies, name
    # Sin sustituto automatico: nunca se descartan por viejos.
    for name in (
        "sync_ibkr_flex",
        "sync_tenant_ibkr_connections",
        "refresh_valuation_metrics",
        "evaluate_dca_signals",
        "run_daily_research",
        "propose_paper_trades",
        "refresh_portfolio_moves",
    ):
        assert policies[name]["stale_after"] is None, name
    # Las ventanas heredan el umbral de obsolescencia (no None).
    assert policies["refresh_bottlenecks"]["stale_after"] is not None


def test_scheduler_fanout_uses_coalesced_send(monkeypatch):
    from app.workers import scheduler as sched

    monkeypatch.setattr(sched, "tenant_contexts", lambda: [(1, "u1"), (2, "u2")])
    calls = []

    def fake_coalesced(actor, *args, **kwargs):
        calls.append((actor.actor_name, args))
        return None if args[0] == 2 else SimpleNamespace(message_id="m1")

    monkeypatch.setattr(sched, "coalesced_send", fake_coalesced)
    actor = SimpleNamespace(actor_name="job")
    result = sched.enqueue_for_all_tenants(actor, scope="tracked")
    assert calls == [("job", (1, "u1")), ("job", (2, "u2"))]
    assert result["queued"][0] == {"tenant_id": 1, "user_id": "u1", "message_id": "m1"}
    assert result["queued"][1] == {"tenant_id": 2, "user_id": "u2", "suppressed": True}
