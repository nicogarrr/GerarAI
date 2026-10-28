"""Cuota LLM de 2o orden (4/min, 100/dia) contra Redis REAL, no el respaldo local.

Patron tomado de tests/test_bounded_broker.py: redis-server desechable en
socket unix por test (skip sin binario; el job `backend` de CI ya instala
redis-server para los tests de admision atomica). Los Settings son de
PRODUCCION (app_env="prod") para ejercitar la rama Redis + Lua de
``app.services.asts_llm_quota.reserve_quota``, que es la que comparten los
namespaces ``second-order`` y ``asts-llm``.

Sin LLM real, sin red externa, sin gasto: solo contadores Redis. La
generacion real con cuota agotada NO se da por probada (alcance 2026-10-28).
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
import redis

from app.core.config import Settings
from app.services import asts_llm_quota as quota_store
from app.services import second_order_quota

SECRET = "0123456789abcdef0123456789abcdef"
# Postgres "fuerte" ficticio, armado por trozos para no parecer credencial real.
PROD_TEST_DATABASE_URL = "postgresql:" + "//app_user" + ":" + "not-a-real-secret-fixture" + "@db:5432/app"


@pytest.fixture
def redis_url(tmp_path):
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("redis-server needed for real-Redis quota tests")
    socket = str(tmp_path / "quota-redis.sock")
    process = subprocess.Popen(
        [binary, "--port", "0", "--unixsocket", socket, "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = redis.Redis(unix_socket_path=socket)
    try:
        for _ in range(100):
            try:
                if client.ping():
                    break
            except redis.RedisError:
                time.sleep(0.02)
        else:
            raise RuntimeError("test Redis did not start")
        yield f"unix://{socket}"
    finally:
        client.close()
        process.terminate()
        process.wait(timeout=5)


def _prod_settings(url: str, **overrides) -> Settings:
    base = dict(
        _env_file=None,
        app_env="prod",
        research_auth_required=True,
        research_auth_secret=SECRET,
        minio_secret_key="production-minio-secret-not-a-default",
        minio_access_key="production-minio-access-not-a-default",
        database_url=PROD_TEST_DATABASE_URL,
        redis_url=url,
    )
    base.update(overrides)
    return Settings(**base)


def _minute_key(tenant: str, namespace: str = "second-order") -> str:
    return f"cavaai:{namespace}:{tenant}:minute:{datetime.now(UTC):%Y%m%d%H%M}"


def _day_key(tenant: str, namespace: str = "second-order") -> str:
    return f"cavaai:{namespace}:{tenant}:day:{datetime.now(UTC):%Y%m%d}"


def test_minute_cap_4_blocks_5th_and_rejection_does_not_consume(redis_url):
    settings = _prod_settings(redis_url)  # defaults reales: 4/min, 100/dia
    assert settings.second_order_llm_calls_per_minute == 4
    assert settings.second_order_llm_calls_per_day == 100
    for expected in range(1, 5):
        result = second_order_quota.reserve_llm_call("t1", settings)
        assert result["allowed"] is True
        assert result["minute_used"] == expected
        assert result["minute_limit"] == 4
    rejected = second_order_quota.reserve_llm_call("t1", settings)
    assert rejected["allowed"] is False
    assert rejected["minute_used"] == 4
    assert rejected["day_used"] == 4
    # Un reintento rechazado no consume ni minuto ni dia (el script Lua no hace INCR).
    again = second_order_quota.reserve_llm_call("t1", settings)
    assert again == rejected


def test_day_cap_100_blocks_101st(redis_url):
    # Minuto al maximo permitido (100) para aislar el tope diario, que es el default real.
    settings = _prod_settings(redis_url, second_order_llm_calls_per_minute=100)
    for _ in range(100):
        assert second_order_quota.reserve_llm_call("t1", settings)["allowed"] is True
    rejected = second_order_quota.reserve_llm_call("t1", settings)
    assert rejected["allowed"] is False
    assert rejected["day_used"] == 100
    assert rejected["day_limit"] == 100


def test_quota_keys_carry_ttl(redis_url):
    settings = _prod_settings(redis_url)
    assert second_order_quota.reserve_llm_call("t1", settings)["allowed"] is True
    client = redis.Redis.from_url(redis_url)
    try:
        minute_ttl = client.ttl(_minute_key("t1"))
        day_ttl = client.ttl(_day_key("t1"))
    finally:
        client.close()
    assert 0 < minute_ttl <= 120
    assert 0 < day_ttl <= 172800


def test_tenant_isolation_with_real_redis(redis_url):
    settings = _prod_settings(redis_url)
    for _ in range(4):
        assert second_order_quota.reserve_llm_call("tenant-a", settings)["allowed"] is True
    assert second_order_quota.reserve_llm_call("tenant-a", settings)["allowed"] is False
    # El tenant agotado no arrastra al vecino: su presupuesto es independiente.
    assert second_order_quota.reserve_llm_call("tenant-b", settings)["allowed"] is True


def test_namespace_isolation_second_order_does_not_starve_asts(redis_url):
    settings = _prod_settings(redis_url)
    for _ in range(4):
        assert second_order_quota.reserve_llm_call("t1", settings)["allowed"] is True
    assert second_order_quota.reserve_llm_call("t1", settings)["allowed"] is False
    # El namespace asts-llm (2/min, 30/dia) tiene su propio presupuesto.
    assert quota_store.reserve_llm_call("t1", settings)["allowed"] is True
    assert quota_store.reserve_llm_call("t1", settings)["allowed"] is True
    assert quota_store.reserve_llm_call("t1", settings)["allowed"] is False


def test_concurrent_reservations_never_exceed_minute_cap(redis_url):
    settings = _prod_settings(redis_url)
    results = []
    lock = threading.Lock()

    def attempt(_):
        outcome = second_order_quota.reserve_llm_call("t1", settings)
        with lock:
            results.append(outcome["allowed"])

    with ThreadPoolExecutor(16) as pool:
        list(pool.map(attempt, range(40)))
    # El script Lua es atomico entre workers: exactamente el cap, ni una mas.
    assert sum(results) == 4
    final = second_order_quota.reserve_llm_call("t1", settings)
    assert final["allowed"] is False
    assert final["minute_used"] == 4
    assert final["day_used"] == 4


def test_redis_down_fails_closed_without_local_fallback(redis_url):
    settings = _prod_settings("unix:///nonexistent-quota.sock")
    # En produccion un Redis caido BLOQUEA la via LLM: excepcion, nunca
    # degradacion silenciosa al contador local en memoria.
    with pytest.raises(redis.RedisError):
        second_order_quota.reserve_llm_call("t1", settings)


def test_minute_window_rolls_and_day_keeps_counting(redis_url, monkeypatch):
    settings = _prod_settings(redis_url)
    real_now = datetime.now(UTC)

    class FakeDateTime(datetime):
        frozen = real_now

        @classmethod
        def now(cls, tz=None):
            return cls.frozen

    monkeypatch.setattr(quota_store, "datetime", FakeDateTime)
    for _ in range(4):
        assert second_order_quota.reserve_llm_call("t1", settings)["allowed"] is True
    assert second_order_quota.reserve_llm_call("t1", settings)["allowed"] is False
    # Ventana deslizante por minuto: el minuto siguiente vuelve a admitir...
    FakeDateTime.frozen = real_now.replace(minute=(real_now.minute + 1) % 60)
    rolled = second_order_quota.reserve_llm_call("t1", settings)
    assert rolled["allowed"] is True
    assert rolled["minute_used"] == 1
    # ...pero el dia acumula (4 + 1): el tope diario no se resetea por minuto.
    assert rolled["day_used"] == 5


def test_missing_tenant_rejected_before_touching_redis(redis_url):
    settings = _prod_settings(redis_url)
    with pytest.raises(RuntimeError, match="verified tenant"):
        second_order_quota.reserve_llm_call(None, settings)
    client = redis.Redis.from_url(redis_url)
    try:
        assert client.keys("cavaai:second-order:*") == []
    finally:
        client.close()
