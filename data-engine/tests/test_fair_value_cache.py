"""Cache Redis del recalculo live de valor justo (resolve_fair_value_cached).

Medido en prod (31-oct): el sondeo de oportunidades de Inicio reprobe la
MISMA lista de candidatas en cada carga y el POST del bundle tardo 6.959 ms;
el recalculo live (motor ValuationService cuando no hay tesis fresca) es el
coste. La cache por (tenant, empresa, dia) evita recalcular entre cargas.

Invariantes:
1. Miss -> calcula y guarda con TTL; hit -> NO recalcula y devuelve igual.
2. Clave por (tenant, empresa, dia): otro tenant u otra empresa recalculan.
3. Redis caido es fail-open: calcula siempre y no propaga la excepcion.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services import fair_value_service as fvs


class FakeRedis:
    def __init__(self, raises=False):
        self.store = {}
        self.raises = raises

    def get(self, key):
        if self.raises:
            raise ConnectionError("redis caido")
        value = self.store.get(key)
        return value.encode() if isinstance(value, str) else value

    def set(self, key, value, ex=None):
        if self.raises:
            raise ConnectionError("redis caido")
        self.store[key] = value
        return True


def _db(tenant_id):
    return SimpleNamespace(info={"tenant_id": tenant_id})


def _company(cid=7):
    return SimpleNamespace(id=cid, ticker="SAN.MC", currency="EUR")


def _reading(cid=7):
    return {"ticker": "SAN.MC", "value": 4.2, "source": "motor", "asOf": date.today().isoformat(), "id": cid}


def _patch(monkeypatch, client, calls):
    monkeypatch.setattr(fvs, "_redis_client", lambda: client, raising=False)
    import app.core.cache as core_cache
    monkeypatch.setattr(core_cache, "_redis_client", lambda: client)
    monkeypatch.setattr(fvs, "resolve_fair_value", lambda db, company, *, live=True, today=None: (calls.append(company.id) or _reading(company.id)))


def test_miss_calcula_y_hit_no_recalcula(monkeypatch):
    client = FakeRedis()
    calls = []
    _patch(monkeypatch, client, calls)
    db, company = _db(2), _company()

    first = fvs.resolve_fair_value_cached(db, company)
    second = fvs.resolve_fair_value_cached(db, company)

    assert calls == [7], "el hit NO debe recalcular el motor"
    assert first == second == _reading()
    key = fvs._live_cache_key(db, company)
    assert key in client.store and key.endswith(date.today().isoformat())


def test_clave_separa_tenant_y_empresa(monkeypatch):
    client = FakeRedis()
    calls = []
    _patch(monkeypatch, client, calls)

    fvs.resolve_fair_value_cached(_db(2), _company(7))
    fvs.resolve_fair_value_cached(_db(3), _company(7))  # otro tenant
    fvs.resolve_fair_value_cached(_db(2), _company(8))  # otra empresa

    assert calls == [7, 7, 8]
    assert len(client.store) == 3


def test_redis_caido_es_fail_open(monkeypatch):
    calls = []
    _patch(monkeypatch, FakeRedis(raises=True), calls)

    reading = fvs.resolve_fair_value_cached(_db(2), _company())
    assert reading == _reading()
    reading2 = fvs.resolve_fair_value_cached(_db(2), _company())
    assert reading2 == _reading()
    assert calls == [7, 7], "sin cache se recalcula cada vez, sin lanzar"
