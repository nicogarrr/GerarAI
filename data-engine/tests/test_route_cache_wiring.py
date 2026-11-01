"""Conexion de la cache Redis a las rutas: hit rate, invalidacion y tenants.

Verifica que la capa de cache de app.core.cache (antes solo cubierta por
tests unitarios) esta realmente conectada:

- GET /api/portfolio/summary y GET /api/watchlist/dca-signals sirven el
  segundo request identico desde cache (misma forma en miss y en hit).
- Las mutaciones invalidan lo cacheado (ruta explicita y listeners ORM
  instalados desde app.models).
- Dos tenants nunca comparten entradas: claves distintas y cero hits cruzados.
- El hit rate medido en /api/cache/stats supera el 70% en trafico repetido.
"""

from __future__ import annotations

import fnmatch
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import main
from app.core import auth as auth_module
from app.core import cache as cache_module
from app.core.cache import cached, get_cache_stats, reset_cache_stats, tenant_from_first_db_arg
from app.core.database import Base, init_db
from app.models import DcaSignalState, Portfolio, Position
from tests.auth_helpers import auth_settings, signed_request

SECRET = "route-cache-wiring-secret-with-at-least-32-chars"


class FakeRedisCache:
    """Redis en memoria con el contrato que usa app.core.cache."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True

    def scan(self, cursor: int = 0, match: str | None = None, count: int = 100):
        pattern = match or "*"
        matched = [k for k in self.store if fnmatch.fnmatch(k, pattern)]
        return 0, matched

    def delete(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                deleted += 1
        return deleted


@pytest.fixture()
def fake_redis():
    fake = FakeRedisCache()
    cache_module._redis_state["client"] = fake
    cache_module._redis_state["down_until"] = 0.0
    reset_cache_stats()
    yield fake
    cache_module._redis_state["client"] = None
    cache_module._redis_state["down_until"] = 0.0
    reset_cache_stats()


@pytest.fixture()
def api(monkeypatch, fake_redis):
    """TestClient firmado por tenant, con Redis falso y sin red."""
    init_db()
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"),
    )
    from app.workers import dramatiq_app

    monkeypatch.setattr(dramatiq_app.broker, "enqueue", lambda message, delay=None: message)
    suffix = uuid4().hex[:8]
    client = TestClient(main.app)

    def call(tenant: str, method: str, path: str, json_body=None, params=None):
        return signed_request(
            client, SECRET, f"{tenant}-{suffix}", f"user-{tenant}-{suffix}",
            method, path, json_body=json_body, params=params,
        )

    ensured = call("a", "POST", "/api/companies/ensure", {"ticker": "MSFT"})
    assert ensured.status_code in (200, 201), ensured.text
    return call


def _buy_msft(call, tenant: str) -> None:
    created = call(tenant, "POST", "/api/portfolio/transactions", {
        "ticker": "MSFT", "action": "buy", "quantity": 3, "price": 100,
        "trade_date": "2024-01-15", "currency": "USD",
    })
    assert created.status_code in (200, 201), created.text


def _summary(call, tenant: str) -> dict:
    resp = call(tenant, "GET", "/api/portfolio/summary")
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestPortfolioSummaryCache:
    def test_second_request_is_cache_hit_with_identical_body(self, api):
        _buy_msft(api, "a")
        reset_cache_stats()

        first = _summary(api, "a")
        second = _summary(api, "a")

        assert first == second
        stats = get_cache_stats()["portfolio_valuation"]
        assert stats["misses"] == 1
        assert stats["hits"] == 1

    def test_repeated_traffic_measures_hit_rate_above_70(self, api):
        _buy_msft(api, "a")
        reset_cache_stats()

        for _ in range(10):
            _summary(api, "a")

        stats = get_cache_stats()["portfolio_valuation"]
        assert stats["total"] == 10
        assert stats["hits"] == 9
        assert stats["hit_rate"] == pytest.approx(90.0)

        exposed = api("a", "GET", "/api/cache/stats")
        assert exposed.status_code == 200, exposed.text
        assert exposed.json()["portfolio_valuation"]["hit_rate"] == pytest.approx(90.0)

    def test_transaction_write_invalidates_cached_summary(self, api):
        _summary(api, "a")  # miss: se cachea
        reset_cache_stats()

        _buy_msft(api, "a")  # listener ORM de Transaction/Position invalida
        _summary(api, "a")

        stats = get_cache_stats()["portfolio_valuation"]
        assert stats["hits"] == 0
        assert stats["misses"] == 1

    def test_tenants_never_share_cache_entries(self, api, fake_redis):
        _buy_msft(api, "a")
        first_a = _summary(api, "a")
        _summary(api, "a")  # hit de A
        stats_before_b = get_cache_stats()["portfolio_valuation"]

        first_b = _summary(api, "b")

        stats = get_cache_stats()["portfolio_valuation"]
        # La primera lectura de B no puede ser hit: sus claves son otras.
        assert stats["hits"] == stats_before_b["hits"]
        assert stats["misses"] == stats_before_b["misses"] + 1
        # Y su contenido no es el de A (B no tiene posiciones).
        assert first_b != first_a

        tenant_parts = {
            key.split(":")[3]
            for key in fake_redis.store
            if key.startswith("portfolio_valuation:")
        }
        assert len(tenant_parts) == 2  # una entrada por tenant, nunca compartida


class TestDcaSignalsCache:
    def _get_signals(self, api, tenant: str) -> dict:
        resp = api(tenant, "GET", "/api/watchlist/dca-signals")
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_second_request_is_cache_hit_with_identical_body(self, api):
        added = api("a", "POST", "/api/watchlist", {"symbol": "MSFT"})
        assert added.status_code in (200, 201), added.text
        reset_cache_stats()

        first = self._get_signals(api, "a")
        second = self._get_signals(api, "a")

        assert first == second
        stats = get_cache_stats()["dca_schedule"]
        assert stats["misses"] == 1
        assert stats["hits"] == 1

    def test_min_level_change_invalidates_cached_payload(self, api):
        added = api("a", "POST", "/api/watchlist", {"symbol": "MSFT"})
        assert added.status_code in (200, 201), added.text
        self._get_signals(api, "a")  # miss: se cachea
        reset_cache_stats()

        changed = api("a", "PUT", "/api/watchlist/MSFT/dca-alert-min-level", {"min_level": 2})
        assert changed.status_code == 200, changed.text
        self._get_signals(api, "a")

        stats = get_cache_stats()["dca_schedule"]
        assert stats["hits"] == 0
        assert stats["misses"] == 1

    def test_watchlist_write_invalidates_cached_payload(self, api):
        self._get_signals(api, "a")  # miss: se cachea
        reset_cache_stats()

        added = api("a", "POST", "/api/watchlist", {"symbol": "MSFT"})
        assert added.status_code in (200, 201), added.text
        self._get_signals(api, "a")

        stats = get_cache_stats()["dca_schedule"]
        assert stats["hits"] == 0
        assert stats["misses"] == 1


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.info["tenant_id"] = 1
    yield session
    session.close()


class TestOrmInvalidationListeners:
    """Los listeners instalados desde app.models cubren las mutaciones que no
    pasan por una ruta (workers, jobs, imports)."""

    def test_dca_state_write_invalidates_dca_cache(self, db_session, fake_redis):
        fake_redis.store["dca_schedule:signals_payload:tenant:1:abc"] = "{}"
        fake_redis.store["portfolio_valuation:risk_dashboard:tenant:1:abc"] = "{}"

        db_session.add(DcaSignalState(tenant_id=1, symbol="MSFT", level=1, status="active",
                                 period="2026-10", signal_date=date(2026, 10, 30),
                                 close=Decimal("150.00"),
                                 params_version="v1", data_source="test"))
        db_session.commit()

        assert not any(k.startswith("dca_schedule:") for k in fake_redis.store)
        # No toca otras categorias.
        assert any(k.startswith("portfolio_valuation:") for k in fake_redis.store)

    def test_position_write_invalidates_portfolio_and_dca_caches(self, db_session, fake_redis):
        fake_redis.store["dca_schedule:signals_payload:tenant:1:abc"] = "{}"
        fake_redis.store["portfolio_valuation:risk_dashboard:tenant:1:abc"] = "{}"
        fake_redis.store["market_data:price:tenant:1:abc"] = "{}"

        portfolio = Portfolio(tenant_id=1, name="Cartera", base_currency="USD", is_default=True)
        db_session.add(portfolio)
        db_session.commit()
        # Portfolio no es Position: solo invalida la categoria cartera.
        assert not any(k.startswith("portfolio_valuation:") for k in fake_redis.store)
        assert any(k.startswith("dca_schedule:") for k in fake_redis.store)

        fake_redis.store["portfolio_valuation:risk_dashboard:tenant:1:abc"] = "{}"
        db_session.add(Position(tenant_id=1, portfolio_id=portfolio.id, company_id=1, quantity=Decimal("1")))
        db_session.commit()

        assert not any(k.startswith("portfolio_valuation:") for k in fake_redis.store)
        assert not any(k.startswith("dca_schedule:") for k in fake_redis.store)
        assert any(k.startswith("market_data:") for k in fake_redis.store)


class TestDeferredInvalidation:
    """La invalidacion se difiere al commit: un flush intermedio no limpia la
    cache y un request concurrente no puede quedarse con el dato viejo."""

    def _two_sessions(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        return factory, factory(), factory()

    def test_flush_alone_does_not_invalidate_commit_does(self, fake_redis):
        factory, writer, _ = self._two_sessions()
        writer.info["tenant_id"] = 1
        fake_redis.store["portfolio_valuation:risk_dashboard:tenant:1:abc"] = "{}"

        portfolio = Portfolio(tenant_id=1, name="Cartera", base_currency="USD", is_default=True)
        writer.add(portfolio)
        writer.flush()  # flush sin commit: la cache sigue intacta
        assert any(k.startswith("portfolio_valuation:") for k in fake_redis.store)

        writer.commit()  # after_commit: ahora si
        assert not any(k.startswith("portfolio_valuation:") for k in fake_redis.store)
        writer.close()

    def test_rollback_discards_pending_invalidation(self, fake_redis):
        factory, writer, _ = self._two_sessions()
        writer.info["tenant_id"] = 1
        fake_redis.store["dca_schedule:signals_payload:tenant:1:abc"] = "{}"

        writer.add(DcaSignalState(tenant_id=1, symbol="MSFT", level=1, status="active",
                                  period="2026-10", signal_date=date(2026, 10, 30),
                                  close=Decimal("150.00"), params_version="v1",
                                  data_source="test"))
        writer.flush()
        writer.rollback()
        assert any(k.startswith("dca_schedule:") for k in fake_redis.store)
        writer.close()

    def test_concurrent_reader_cannot_keep_stale_value(self, db_session, fake_redis):
        """Carrera del diseno anterior: A escribe y hace flush, B lee el dato
        viejo y lo cachea, A commitea. Con invalidacion en after_commit la
        entrada cacheada por B se borra al commitear A."""
        factory, writer, reader = self._two_sessions()
        writer.info["tenant_id"] = 1
        reader.info["tenant_id"] = 1

        portfolio = Portfolio(tenant_id=1, name="Cartera", base_currency="USD", is_default=True)
        writer.add(portfolio)
        writer.flush()  # A: datos nuevos aun no visibles para B

        # B (otra sesion) lee el estado VIEJO y lo cachea bajo la misma clave.
        fake_redis.store["portfolio_valuation:risk_dashboard:tenant:1:abc"] = (
            '{"total_value": 0}'
        )
        writer.commit()  # A confirma: la entrada vieja de B tiene que salir.

        assert not any(k.startswith("portfolio_valuation:") for k in fake_redis.store)
        writer.close()
        reader.close()


class TestJsonShapeConsistency:
    def test_miss_and_hit_return_identical_shape(self, db_session, fake_redis):
        calls = {"n": 0}

        @cached(prefix="test:shape", ttl=60, category="market_data",
                extract_tenant=tenant_from_first_db_arg)
        def compute(db: Session) -> dict:
            calls["n"] += 1
            return {
                "amount": Decimal("12.34"),
                "day": date(2026, 1, 2),
                "at": datetime(2026, 1, 2, 3, 4, 5),
            }

        first = compute(db_session)
        second = compute(db_session)

        assert calls["n"] == 1
        assert first == second == {
            "amount": 12.34,
            "day": "2026-01-02",
            "at": "2026-01-02T03:04:05",
        }

    def test_unserializable_result_fails_open_uncached(self, db_session, fake_redis):
        calls = {"n": 0}

        @cached(prefix="test:circular", ttl=60, category="market_data",
                extract_tenant=tenant_from_first_db_arg)
        def compute(db: Session) -> dict:
            calls["n"] += 1
            payload: dict = {"n": calls["n"]}
            payload["self"] = payload  # referencia circular: no serializable
            return payload

        first = compute(db_session)
        second = compute(db_session)

        # Nunca rompe la respuesta; simplemente no cachea.
        assert first["n"] == 1
        assert second["n"] == 2
        assert not any(k.startswith("test:circular") for k in fake_redis.store)

    def test_function_style_tenant_extractor(self, db_session):
        assert tenant_from_first_db_arg((db_session,), {}) == 1
        assert tenant_from_first_db_arg((), {"db": db_session}) == 1
        assert tenant_from_first_db_arg((), {}) is None
