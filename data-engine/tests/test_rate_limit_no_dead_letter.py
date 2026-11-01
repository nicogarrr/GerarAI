"""429 sin dead-letter: backoff exponencial con jitter y descarte en el ultimo intento.

Lectura de dead-letter en prod (1-nov-2026): 59 refresh_macro_news y 23
refresh_news con «GDELT cerro la ventana (429): lote reencolado tras 60s».
Con espera fija de 60 s los 6 reintentos se agotaban en ~6 min contra una
ventana aun cerrada y el lote acababa en la cola XQ, aunque el siguiente tick
del scheduler lo reponia igual.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import dramatiq
import pytest

from app.workers import dramatiq_app
from app.workers.dramatiq_app import GDELT_CIRCUIT_TTL_SECONDS, _handle_actor_error, _raise_gdelt_retry
from app.workers.rate_limit_retry import (
    RateLimitRetriesExhausted,
    backoff_seconds,
    retry_budget,
    retry_or_drop,
)


def _current(monkeypatch, *, retries=None, eta=False, actor_name=None, max_retries=None):
    options = {}
    if retries is not None:
        options["retries"] = retries
    if eta:
        options["eta"] = 123
    if max_retries is not None:
        options["max_retries"] = max_retries
    message = SimpleNamespace(options=options, actor_name=actor_name, message_timestamp=time.time() * 1000)
    monkeypatch.setattr(dramatiq_app.CurrentMessage, "get_current_message", classmethod(lambda cls: message))
    return message


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

    def exists(self, key):
        return int(key in self.store)

    def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    def expire(self, key, seconds):
        return True

    def eval(self, script, numkeys, key, token):
        if self.store.get(key) == token:
            self.store.pop(key)
            return 1
        return 0


# ---------- politica comun ----------


def test_backoff_crece_por_intento_con_techo():
    no_jitter = {"jitter_ratio": 0.0}
    assert backoff_seconds(0, base=60, cap=1800, **no_jitter) == 60
    assert backoff_seconds(1, base=60, cap=1800, **no_jitter) == 120
    assert backoff_seconds(3, base=60, cap=1800, **no_jitter) == 480
    assert backoff_seconds(5, base=60, cap=1800, **no_jitter) == 1800
    assert backoff_seconds(99, base=60, cap=1800, **no_jitter) == 1800


def test_backoff_honra_retry_after_sin_truncarlo():
    no_jitter = {"jitter_ratio": 0.0}
    # Primer intento: la ventana del servidor tal cual, aunque sea corta.
    assert backoff_seconds(0, base=60, cap=1800, retry_after=30, **no_jitter) == 30
    # Ventana mayor que el techo: manda el servidor.
    assert backoff_seconds(4, base=60, cap=1800, retry_after=3600, **no_jitter) == 3600
    # Ventana menor que el crecimiento: manda el crecimiento.
    assert backoff_seconds(3, base=60, cap=1800, retry_after=45, **no_jitter) == 480
    # Ventana absurda: se ignora.
    assert backoff_seconds(0, base=60, cap=1800, retry_after=float("nan"), **no_jitter) == 60


def test_backoff_jitter_acotado():
    assert backoff_seconds(0, base=100, cap=1000, rng=lambda: 0.0) == 100
    assert backoff_seconds(0, base=100, cap=1000, rng=lambda: 0.999) == pytest.approx(119.98)


def test_retry_budget_lee_max_retries_del_actor(monkeypatch):
    _current(monkeypatch, retries=4, actor_name="refresh_macro_news")
    assert retry_budget() == (4, dramatiq_app.refresh_macro_news.options["max_retries"])


def test_retry_or_drop_reencola_si_queda_presupuesto(monkeypatch):
    _current(monkeypatch, retries=2, max_retries=6)
    with pytest.raises(dramatiq.Retry) as caught:
        retry_or_drop("fuente", base=60, cap=1800)
    assert 240_000 <= caught.value.delay < 288_000


def test_retry_or_drop_descarta_en_el_ultimo_intento(monkeypatch):
    _current(monkeypatch, retries=6, max_retries=6)
    with pytest.raises(RateLimitRetriesExhausted):
        retry_or_drop("fuente", base=60, cap=1800)


def test_handle_actor_error_no_manda_a_dead_letter_el_descarte():
    result = _handle_actor_error("refresh_news", RateLimitRetriesExhausted("GDELT", 6, 6))
    assert result["status"] == "skipped"
    assert result["reason"] == "rate_limited_retries_exhausted"


# ---------- GDELT ----------


def test_gdelt_429_repetido_espera_cada_vez_mas(monkeypatch):
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: None)
    exc = Exception("429")
    exc.retry_after = 60.0
    _current(monkeypatch, retries=3, max_retries=6)
    with pytest.raises(dramatiq.Retry) as caught:
        _raise_gdelt_retry(exc)
    # Antes: 60 s fijos en cada reintento (6 reintentos = 6 min).
    assert caught.value.delay >= 480_000


def test_gdelt_429_en_el_ultimo_intento_no_va_a_dead_letter(monkeypatch):
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: None)
    exc = Exception("429")
    exc.retry_after = 60.0
    _current(monkeypatch, retries=6, actor_name="refresh_news")
    with pytest.raises(RateLimitRetriesExhausted):
        _raise_gdelt_retry(exc)


def test_macro_429_en_el_ultimo_intento_termina_en_skipped(monkeypatch):
    import app.services.feed_ingestion_service as fis
    from app.services.connectors.gdelt import GdeltRateLimited

    class _Service:
        async def poll_gdelt(self, query, *, ticker=None, max_records=15):
            raise GdeltRateLimited(60.0)

    class _DB:
        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: _DB())
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda *a, **k: object())
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda *a, **k: None)
    monkeypatch.setattr(fis, "FeedIngestionService", lambda: _Service())
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: _Redis())
    _current(monkeypatch, retries=6, actor_name="refresh_macro_news")
    result = dramatiq_app.refresh_macro_news(tenant_id=3, user_id="u1")
    assert result["status"] == "skipped"
    assert result["reason"] == "rate_limited_retries_exhausted"


def test_disyuntor_abierto_en_el_ultimo_intento_se_descarta_en_silencio(monkeypatch):
    client = _Redis()
    client.set("gdelt:circuit:open", "1")
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: client)
    _current(monkeypatch, retries=6, actor_name="refresh_news")
    result = dramatiq_app.refresh_news.fn(None, None)
    assert result["status"] == "skipped"
    assert result["reason"] == "gdelt_circuit_open"


def test_disyuntor_abierto_con_presupuesto_reprograma_con_jitter(monkeypatch):
    client = _Redis()
    client.set("gdelt:circuit:open", "1")
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: client)
    _current(monkeypatch, retries=1, actor_name="refresh_macro_news")
    with pytest.raises(dramatiq.Retry) as caught:
        dramatiq_app.refresh_macro_news.fn(None, None)
    ttl_ms = GDELT_CIRCUIT_TTL_SECONDS * 1000
    assert ttl_ms <= caught.value.delay < ttl_ms * 1.2
