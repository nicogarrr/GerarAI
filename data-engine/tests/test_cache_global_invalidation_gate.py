"""Gate de la invalidacion GLOBAL de cache de mercado (B-seguridad).

La cache de mercado (Redis, prefijo market_data) es COMPARTIDA entre
tenants: un POST /api/cache/invalidate/market-data o /invalidate/all la
vaciaba para todos con cualquier identidad firmada. La accion queda detras
de ``cache_global_invalidation_allowed``: activo por defecto fuera de
produccion, apagado en produccion salvo CACHE_GLOBAL_INVALIDATION_ENABLED
explicita. Con el gate cerrado la ruta responde 404 (como si no existiera)
y la accion sigue disponible como script de ops
(scripts/invalidate_market_cache.py).
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.api.routes import cache as cache_routes
from app.core import auth as auth_module
from app.core.config import Settings
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "cache-gate-test-secret-at-least-32-chars-ok"


def _settings_ns(*, allowed: bool) -> SimpleNamespace:
    return SimpleNamespace(cache_global_invalidation_allowed=allowed)


def _client(monkeypatch, *, allowed: bool) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    monkeypatch.setattr(cache_routes, "get_settings", lambda: _settings_ns(allowed=allowed))
    init_db()
    tenant_ext = f"cache-gate-{uuid4().hex[:8]}"
    other_ext = f"cache-gate-other-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Gate A"))
    db.add(Tenant(external_id=other_ext, name="Gate B"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, other_ext


# model_construct: la validacion completa de produccion exige secretos
# ajenos al gate (MINIO_SECRET_KEY, etc.); aqui solo importa la resolucion
# del flag sobre app_env.
def test_flag_default_off_in_production():
    s = Settings.model_construct(app_env="production")
    assert s.is_production is True
    assert s.cache_global_invalidation_allowed is False


def test_flag_default_on_outside_production():
    assert Settings.model_construct(app_env="test").cache_global_invalidation_allowed is True
    assert Settings.model_construct(app_env="local").cache_global_invalidation_allowed is True


def test_flag_explicit_override_wins():
    assert (
        Settings.model_construct(
            app_env="production", cache_global_invalidation_enabled=True
        ).cache_global_invalidation_allowed
        is True
    )
    assert (
        Settings.model_construct(
            app_env="test", cache_global_invalidation_enabled=False
        ).cache_global_invalidation_allowed
        is False
    )


def test_market_data_invalidate_404_when_gate_closed(monkeypatch):
    client, tenant, _ = _client(monkeypatch, allowed=False)
    calls: list[str] = []
    monkeypatch.setattr(cache_routes, "invalidate_market_data_cache", lambda: calls.append("x"))
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/cache/invalidate/market-data")
    assert res.status_code == 404, res.text
    assert calls == []


def test_invalidate_all_404_when_gate_closed(monkeypatch):
    client, tenant, _ = _client(monkeypatch, allowed=False)
    calls: list[str] = []
    monkeypatch.setattr(cache_routes, "invalidate_market_data_cache", lambda: calls.append("x"))
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/cache/invalidate/all")
    assert res.status_code == 404, res.text
    assert calls == []


def test_gate_closed_for_every_tenant(monkeypatch):
    """Ningun tenant (propio o ajeno) vacia la cache global con el gate cerrado."""
    client, tenant, other = _client(monkeypatch, allowed=False)
    calls: list[str] = []
    monkeypatch.setattr(cache_routes, "invalidate_market_data_cache", lambda: calls.append("x"))
    for t in (tenant, other):
        res = signed_request(client, SECRET, t, "u1", "POST", "/api/cache/invalidate/market-data")
        assert res.status_code == 404, res.text
    assert calls == []


def test_market_data_invalidate_ok_when_gate_open(monkeypatch):
    client, tenant, _ = _client(monkeypatch, allowed=True)
    calls: list[str] = []
    monkeypatch.setattr(cache_routes, "invalidate_market_data_cache", lambda: calls.append("x"))
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/cache/invalidate/market-data")
    assert res.status_code == 200, res.text
    assert calls == ["x"]


def test_invalidate_all_ok_when_gate_open(monkeypatch):
    client, tenant, _ = _client(monkeypatch, allowed=True)
    monkeypatch.setattr(cache_routes, "invalidate_market_data_cache", lambda: None)
    monkeypatch.setattr(cache_routes, "invalidate_portfolio_cache", lambda db: None)
    monkeypatch.setattr(cache_routes, "invalidate_dca_cache", lambda db: None)
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/cache/invalidate/all")
    assert res.status_code == 200, res.text


def test_tenant_scoped_invalidations_unaffected_when_gate_closed(monkeypatch):
    """Las invalidaciones por tenant (portfolio/dca) NO van detras del gate."""
    client, tenant, _ = _client(monkeypatch, allowed=False)
    monkeypatch.setattr(cache_routes, "invalidate_portfolio_cache", lambda db: None)
    monkeypatch.setattr(cache_routes, "invalidate_dca_cache", lambda db: None)
    for path in ("/api/cache/invalidate/portfolio", "/api/cache/invalidate/dca"):
        res = signed_request(client, SECRET, tenant, "u1", "POST", path)
        assert res.status_code == 200, res.text


# --- Contrato verificable del borrado (retencion del piloto en #3574) ---
#
# invalidate_market_data_cache devolvia None siempre y tragaba los fallos:
# el script de ops salia 0 sin haber borrado nada. Ahora devuelve el numero
# de claves borradas, o None si Redis no esta disponible o el borrado falla
# (los llamadores que ignoran el retorno no cambian de comportamiento).

import app.core.cache as cache_core
from scripts import invalidate_market_cache as invalidate_script


class _FakeRedis:
    def __init__(self, keys: list[str], *, fail_scan: bool = False):
        self._keys = keys
        self._fail_scan = fail_scan
        self.deleted: list[str] = []

    def scan(self, cursor: int, match: str, count: int):
        if self._fail_scan:
            raise ConnectionError("redis down")
        return 0, list(self._keys)

    def delete(self, *keys: str) -> int:
        self.deleted.extend(keys)
        return len(keys)


def test_invalidate_returns_none_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(cache_core, "_redis_client", lambda: None)
    assert cache_core.invalidate_market_data_cache() is None


def test_invalidate_counts_deleted_keys(monkeypatch):
    fake = _FakeRedis(["k1", "k2", "k3"])
    monkeypatch.setattr(cache_core, "_redis_client", lambda: fake)
    assert cache_core.invalidate_market_data_cache() == 3
    assert fake.deleted == ["k1", "k2", "k3"]


def test_invalidate_zero_keys_is_success(monkeypatch):
    fake = _FakeRedis([])
    monkeypatch.setattr(cache_core, "_redis_client", lambda: fake)
    assert cache_core.invalidate_market_data_cache() == 0


def test_invalidate_returns_none_on_error(monkeypatch):
    fake = _FakeRedis([], fail_scan=True)
    monkeypatch.setattr(cache_core, "_redis_client", lambda: fake)
    assert cache_core.invalidate_market_data_cache() is None


def test_script_exit_1_when_redis_unavailable(monkeypatch, capsys):
    monkeypatch.setattr(cache_core, "invalidate_market_data_cache", lambda: None)
    assert invalidate_script.main() == 1
    assert "no disponible" in capsys.readouterr().err.lower()


def test_script_prints_count_and_exits_0(monkeypatch, capsys):
    monkeypatch.setattr(cache_core, "invalidate_market_data_cache", lambda: 7)
    assert invalidate_script.main() == 0
    assert "7" in capsys.readouterr().out


def test_script_zero_keys_exits_0(monkeypatch, capsys):
    monkeypatch.setattr(cache_core, "invalidate_market_data_cache", lambda: 0)
    assert invalidate_script.main() == 0
    assert "0" in capsys.readouterr().out
