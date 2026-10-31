"""Cache Redis compartida (L2) del material de resultados de seguidas.

La cache en memoria (L1) vive por worker de gunicorn: cada worker frio
repetia las llamadas a la SEC para los mismos eventos y el endpoint
/api/calendar/followed/materials media 2.346 ms en el barrido del piloto
(2026-10-31). Redis comparte aciertos entre workers y usuarios con los
MISMOS TTL por estado (ok 24 h / miss 10 min) que la L1. Redis caido ->
fail-open: se resuelve contra la SEC como antes.
"""

import asyncio
import json
from datetime import date

from app.services import earnings_materials_service as svc

OK_VALUE = {"status": "ok", "links": [{"kind": "press_release", "url": "https://sec.gov/x"}]}
MISS_VALUE = {"status": "no_disponible"}


class FakeRedis:
    def __init__(self, values=None, exc=None, pttl_ms=None):
        self.values = dict(values or {})
        self.exc = exc
        self.set_calls = []
        self._pttl_ms = pttl_ms

    def get(self, key):
        if self.exc:
            raise self.exc
        return self.values.get(key)

    def pttl(self, key):
        if self.exc:
            raise self.exc
        return self._pttl_ms if self._pttl_ms is not None else -1

    def set(self, key, value, ex=None):
        if self.exc:
            raise self.exc
        self.set_calls.append((key, ex, value))
        self.values[key] = value


class BoomSEC:
    """Si alguien llama a la SEC en un test de hit, el test debe fallar."""

    async def cik_for_ticker(self, ticker):  # pragma: no cover - no debe llamarse
        raise AssertionError("SEC llamada pese al hit de Redis")


def _events():
    return [{"ticker": "TSLA", "date": "2026-07-22", "fiscal_label": "Jun/2026", "confirmed": True}]


def setup_function():
    svc.reset_cache()


def teardown_function():
    svc.reset_cache()


def test_redis_hit_skips_sec_and_refills_memory(monkeypatch):
    redis = FakeRedis({svc._materials_redis_key("TSLA|2026-07-22"): json.dumps(OK_VALUE)})
    monkeypatch.setattr(svc, "_materials_redis", lambda: redis)

    out = asyncio.run(svc.materials_for_events(_events(), date(2026, 7, 24), sec=BoomSEC()))

    assert out == {"TSLA|2026-07-22": OK_VALUE}
    # L1 rellenada: una segunda llamada no consulta ni Redis ni SEC.
    monkeypatch.setattr(svc, "_materials_redis", lambda: FakeRedis(exc=RuntimeError("caido")))
    out2 = asyncio.run(svc.materials_for_events(_events(), date(2026, 7, 24), sec=BoomSEC()))
    assert out2 == {"TSLA|2026-07-22": OK_VALUE}


def test_resolved_value_is_written_to_redis_with_status_ttl(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(svc, "_materials_redis", lambda: redis)

    class FakeResolverSEC:
        async def cik_for_ticker(self, ticker):
            raise RuntimeError("sin red")

    out = asyncio.run(svc.materials_for_events(_events(), date(2026, 7, 24), sec=FakeResolverSEC()))

    # Sin CIK el resultado es no_disponible (MISS): TTL corto de 10 min.
    assert out["TSLA|2026-07-22"]["status"] == "no_disponible"
    assert redis.set_calls == [
        (svc._materials_redis_key("TSLA|2026-07-22"), svc.MISS_TTL_S, json.dumps(out["TSLA|2026-07-22"]))
    ]


def test_redis_down_fail_open_still_resolves(monkeypatch):
    monkeypatch.setattr(svc, "_materials_redis", lambda: None)

    class FakeResolverSEC:
        async def cik_for_ticker(self, ticker):
            raise RuntimeError("sin red")

    out = asyncio.run(svc.materials_for_events(_events(), date(2026, 7, 24), sec=FakeResolverSEC()))

    assert out["TSLA|2026-07-22"]["status"] == "no_disponible"


def test_redis_error_on_read_and_write_never_breaks(monkeypatch):
    redis = FakeRedis(exc=RuntimeError("redis caido"))
    monkeypatch.setattr(svc, "_materials_redis", lambda: redis)

    class FakeResolverSEC:
        async def cik_for_ticker(self, ticker):
            raise RuntimeError("sin red")

    out = asyncio.run(svc.materials_for_events(_events(), date(2026, 7, 24), sec=FakeResolverSEC()))

    assert out["TSLA|2026-07-22"]["status"] == "no_disponible"


def test_redis_hit_rehydrates_memory_with_remaining_ttl(monkeypatch):
    """L2->L1 conserva la frescura: un MISS a 100 s de expirar en Redis no
    puede renacer con 10 min completos en la L1 del worker (auditoria piloto:
    antes llegaba a 10+10 min de antiguedad)."""
    import time

    redis = FakeRedis(
        {svc._materials_redis_key("TSLA|2026-07-22"): json.dumps(MISS_VALUE)},
        pttl_ms=100_000,  # quedan 100 s de los 600 s del MISS
    )
    monkeypatch.setattr(svc, "_materials_redis", lambda: redis)

    out = asyncio.run(svc.materials_for_events(_events(), date(2026, 7, 24), sec=BoomSEC()))

    assert out == {"TSLA|2026-07-22": MISS_VALUE}
    stored_at = svc._cache["TSLA|2026-07-22"][0]
    age_s = time.monotonic() - stored_at
    # La L1 hereda la edad de la entrada de Redis: ~500 s consumidos, no 0.
    assert age_s >= 499.0, f"L1 rehidratada con TTL completo (edad {age_s:.1f} s)"
    assert age_s <= svc.MISS_TTL_S
