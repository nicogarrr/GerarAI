"""sync_official_closes con sesion SQLite real: lock estricto en Redis
(sin fallback local), marcador de sesion ya sincronizada, presupuesto de
3 descargas por ventana de 6h con cooldown, marcador done solo con
cobertura suficiente y fecha exacta, y release del lock en todos los
caminos. Solo se sustituyen Redis, la red (el servicio) y el reloj."""

import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.market_close_sync as mcs
from app.models.entities import Base
from app.workers import dramatiq_app as worker


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.releases = []
        self.closed = False

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def eval(self, script, nkeys, *args):
        self.releases.append(args)
        return 1

    def close(self):
        self.closed = True


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    e = SimpleNamespace(db=db, redis=FakeRedis(), sync_result=None, sync_error=None,
                        sync_calls=0)
    monkeypatch.setattr(worker, "_redis_client", lambda: e.redis)
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)

    def fake_sync(db_):
        e.sync_calls += 1
        if e.sync_error is not None:
            raise e.sync_error
        return e.sync_result

    monkeypatch.setattr(mcs, "sync_official_closes", fake_sync)
    e.session_key = worker._official_close_session_key()
    return e


def _ok_result(env, coverage=0.95, date=None):
    return {"status": "ok", "target_coverage": coverage,
            "target_date": date or env.session_key, "target_covered": 10,
            "with_symbol": 10, "failed_chunks": 0, "target_missing": 0}


def test_sin_redis_es_error_duro(env, monkeypatch):
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    with pytest.raises(RuntimeError):
        worker.sync_official_closes.fn(tenant_id=1, user_id="u")


def test_lock_en_curso_skips(env):
    env.redis.store["cavaai:job-lease:sync_official_closes:global"] = "otro"
    out = worker.sync_official_closes.fn(tenant_id=1, user_id="u")
    assert out["status"] == "skipped" and out["reason"] == "lease_held"
    assert env.sync_calls == 0 and env.redis.closed


def test_sesion_ya_sincronizada_skips(env):
    env.redis.set("cavaai:official-closes:done:" + env.session_key, "1")
    out = worker.sync_official_closes.fn(tenant_id=1, user_id="u")
    assert out["reason"] == "session_already_synced" and env.sync_calls == 0
    assert env.redis.releases  # el lock se suelta


def test_tres_intentos_inician_cooldown(env):
    env.redis.set("cavaai:official-closes:attempts:" + env.session_key, "3")
    out = worker.sync_official_closes.fn(tenant_id=1, user_id="u")
    assert out["reason"] == "session_attempt_cooldown"
    assert out["attempts"] == 3 and out["retry_after_seconds"] > 0
    assert env.sync_calls == 0


def test_cooldown_expirado_reanuda_con_contador_a_cero(env, monkeypatch):
    env.redis.set("cavaai:official-closes:attempts:" + env.session_key, "3")
    env.redis.set("cavaai:official-closes:cooldown-start:" + env.session_key,
                  str(int(time.time()) - 7 * 3600))
    env.sync_result = _ok_result(env)
    out = worker.sync_official_closes.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and env.sync_calls == 1
    assert env.redis.get("cavaai:official-closes:done:" + env.session_key) == "1"


def test_exito_con_cobertura_marca_done_y_libera(env):
    env.sync_result = _ok_result(env)
    out = worker.sync_official_closes.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["actor"] == "sync_official_closes"
    assert env.redis.get("cavaai:official-closes:done:" + env.session_key) == "1"
    assert env.redis.get("cavaai:official-closes:attempts:" + env.session_key) == "1"
    assert env.redis.releases and env.redis.closed


def test_cobertura_baja_no_marca_done(env):
    env.sync_result = _ok_result(env, coverage=0.5)
    out = worker.sync_official_closes.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok"
    assert env.redis.get("cavaai:official-closes:done:" + env.session_key) is None


def test_fecha_distinta_no_marca_done(env):
    env.sync_result = _ok_result(env, date="2001-01-01")
    worker.sync_official_closes.fn(tenant_id=1, user_id="u")
    assert env.redis.get("cavaai:official-closes:done:" + env.session_key) is None


def test_error_del_servicio_rollback_propaga_y_libera(env):
    env.sync_error = RuntimeError("proveedor caido")
    with pytest.raises(RuntimeError):
        worker.sync_official_closes.fn(tenant_id=1, user_id="u")
    assert env.redis.releases and env.redis.closed


def test_tercer_intento_precarga_el_cooldown(env):
    env.redis.set("cavaai:official-closes:attempts:" + env.session_key, "2")
    env.sync_result = _ok_result(env)
    worker.sync_official_closes.fn(tenant_id=1, user_id="u")
    assert env.redis.get("cavaai:official-closes:attempts:" + env.session_key) == "3"
    # La ventana de 6h empieza ya: un 4.0 mensaje en cola no descarga mas.
    assert env.redis.get("cavaai:official-closes:cooldown-start:" + env.session_key)


def test_redis_caido_a_mitad_propaga_sin_tocar_sesion(env, monkeypatch):
    class RedisRoto(FakeRedis):
        def set(self, key, value, nx=False, ex=None):
            if key.startswith("cavaai:official-closes:attempts"):
                raise RuntimeError("redis caido a mitad")
            return super().set(key, value, nx=nx, ex=ex)

    env.redis = RedisRoto()
    monkeypatch.setattr(worker, "_redis_client", lambda: env.redis)
    with pytest.raises(RuntimeError):
        worker.sync_official_closes.fn(tenant_id=1, user_id="u")
    assert env.sync_calls == 0  # nunca llego al servicio
    assert env.redis.releases  # pero el lock se libera
