"""Bordes de app/services/cached_dca_schedule.py (zona levantada por Nico 9-nov-2026 18:43).

La suite de redis cubre el camino feliz de get_dca_signals (caché miss/hit). Aquí se cubren el resto
de métodos y las ramas de nivel de precio con el mismo patrón aprobado (SQLite en memoria +
FakeRedisCache de tests/test_redis_caching.py):

- _extract_tenant_from_db (sin db, db sin info, info sin tenant, con tenant);
- get_dca_signals: level_prices vacío, nivel ausente del dict, valor no convertible (ValueError);
- get_dca_signal: símbolo inexistente (None), metadata con metrics y con metrics vacío, valor de
  nivel no convertible;
- get_watchlist_dca_signals: watchlist vacía, orden por nivel descendente, símbolo fuera de la
  watchlist excluido;
- get_portfolio_dca_signals: sin posiciones, posición sin empresa excluida, payload sin verdict_month;
- invalidate_cache: la siguiente llamada vuelve a ser miss.
"""

import contextlib
import copy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import cache as cache_module
from app.core.cache import get_cache_stats, reset_cache_stats
from app.core.database import Base
from app.models import Company, DcaSignalState, Portfolio, Position, WatchItem
from app.services import portfolio_fx_service as pfx
from app.services.cached_dca_schedule import CachedDcaScheduleService, _extract_tenant_from_db
from tests.test_redis_caching import FakeRedisCache

HOY = date(2026, 11, 9)  # dato opaco: el servicio no filtra por fecha


def _redis_fake():
    """FakeRedis con snapshot+restore del estado global previo (no fuerza None al salir)."""
    prev_client = cache_module._redis_state["client"]
    prev_down = cache_module._redis_state["down_until"]
    fake = FakeRedisCache()
    cache_module._redis_state["client"] = fake
    cache_module._redis_state["down_until"] = 0.0
    try:
        yield fake
    finally:
        cache_module._redis_state["client"] = prev_client
        cache_module._redis_state["down_until"] = prev_down


@pytest.fixture(autouse=True)
def mock_redis_cache():
    yield from _redis_fake()


@contextlib.contextmanager
def _stats_aisladas():
    """Las métricas globales de caché vuelven a sus valores previos al salir del bloque."""
    with cache_module._stats_lock:
        prev = copy.deepcopy(cache_module._cache_stats)
    try:
        yield
    finally:
        with cache_module._stats_lock:
            cache_module._cache_stats.clear()
            cache_module._cache_stats.update(prev)


def test_fixture_redis_restaura_el_estado_previo():
    prev_client = cache_module._redis_state["client"]
    prev_down = cache_module._redis_state["down_until"]
    centinela = object()
    cache_module._redis_state["client"] = centinela
    cache_module._redis_state["down_until"] = 999.0
    gen = _redis_fake()
    fake = next(gen)
    assert cache_module._redis_state["client"] is fake
    gen.close()  # ejecuta el finally: restaura el centinela, no None
    assert cache_module._redis_state["client"] is centinela
    assert cache_module._redis_state["down_until"] == 999.0
    cache_module._redis_state["client"] = prev_client
    cache_module._redis_state["down_until"] = prev_down


def test_stats_aisladas_restaura_los_contadores_previos():
    antes = get_cache_stats()["dca_schedule"]["misses"]
    with _stats_aisladas():
        reset_cache_stats()
        cache_module._record_miss("dca_schedule")
        assert get_cache_stats()["dca_schedule"]["misses"] == 1
    assert get_cache_stats()["dca_schedule"]["misses"] == antes


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.info["tenant_id"] = 1
    yield session
    session.close()


def _signal(symbol, level=2, *, close="150.00", level_prices=None, metrics=None, tenant=1):
    return DcaSignalState(
        tenant_id=tenant,
        symbol=symbol,
        level=level,
        status="active",
        period="2026-11",
        signal_date=HOY,
        close=Decimal(close),
        level_prices=level_prices if level_prices is not None else {"2": "145.00"},
        metrics=metrics if metrics is not None else {},
        params_version="v1",
        data_source="test",
    )


def test_extract_tenant_bordes():
    assert _extract_tenant_from_db((), {}) is None  # sin argumentos
    assert _extract_tenant_from_db((object(),), {}) is None  # sin db
    assert _extract_tenant_from_db((object(), object()), {}) is None  # db sin info
    assert _extract_tenant_from_db((object(), SimpleNamespace(info={})), {}) is None  # info sin tenant
    assert _extract_tenant_from_db((object(), SimpleNamespace(info={"tenant_id": 7})), {}) == 7


def test_get_dca_signals_ramas_de_level_price(db_session):
    db_session.add_all(
        [
            _signal("AAA", 2),  # feliz: "2" -> 145.00
            _signal("BBB", 1, level_prices={}),  # dict vacío: sin precio de nivel
            _signal("CCC", 3, level_prices={"2": "140.00"}),  # nivel ausente del dict
            _signal("DDD", 2, level_prices={"2": "no-es-numero"}),  # ValueError -> None
        ]
    )
    db_session.commit()
    out = {r["symbol"]: r for r in CachedDcaScheduleService().get_dca_signals(db_session)}
    assert out["AAA"]["level_price"] == 145.0
    assert out["BBB"]["level_price"] is None
    assert out["CCC"]["level_price"] is None
    assert out["DDD"]["level_price"] is None
    assert out["AAA"]["current_price"] == 150.0 and out["AAA"]["verdict_month"] == "2026-11"


def test_get_dca_signal_inexistente_y_metadata(db_session):
    service = CachedDcaScheduleService()
    assert service.get_dca_signal(db_session, "NOPE") is None
    db_session.add(_signal("AAA", 2, metrics={"source": "cerebro"}))
    db_session.add(_signal("BBB", 1, metrics={}))
    db_session.commit()
    con = service.get_dca_signal(db_session, "AAA")
    assert con["metadata"] == {"source": "cerebro"} and con["level_price"] == 145.0
    sin = service.get_dca_signal(db_session, "BBB")
    assert sin["metadata"] == {} and sin["level_price"] is None  # level 1 no está en level_prices


def test_get_dca_signal_valor_de_nivel_no_convertible(db_session):
    db_session.add(_signal("AAA", 2, level_prices={"2": "mil"}))
    db_session.commit()
    assert CachedDcaScheduleService().get_dca_signal(db_session, "AAA")["level_price"] is None


def test_get_dca_signal_sin_level_prices(db_session):
    db_session.add(_signal("AAA", 2, level_prices={}))  # dict vacío: ni se consulta el nivel
    db_session.commit()
    assert CachedDcaScheduleService().get_dca_signal(db_session, "AAA")["level_price"] is None


def test_watchlist_vacia(db_session):
    assert CachedDcaScheduleService().get_watchlist_dca_signals(db_session) == []


def test_watchlist_orden_y_exclusion(db_session):
    db_session.add_all(
        [
            WatchItem(symbol="AAA", tenant_id=1),
            WatchItem(symbol="BBB", tenant_id=1),
            WatchItem(symbol="CCC", tenant_id=1),
            WatchItem(symbol="DDD", tenant_id=1),
            WatchItem(symbol="EEE", tenant_id=1),
        ]
    )
    db_session.add_all(
        [
            _signal("AAA", 1),
            _signal("BBB", 3),
            _signal("CCC", 2),  # nivel presente en el dict: float() se ejecuta
            _signal("DDD", 2, level_prices={"2": "mucho"}),  # valor no convertible -> None
            _signal("EEE", 5, level_prices={}),  # dict vacío: ni se consulta el nivel
            _signal("ZZZ", 2),  # ZZZ fuera de la watchlist
        ]
    )
    db_session.commit()
    out = CachedDcaScheduleService().get_watchlist_dca_signals(db_session)
    assert [r["symbol"] for r in out] == ["EEE", "BBB", "CCC", "DDD", "AAA"]  # nivel descendente
    assert all(
        set(r) == {"symbol", "current_level", "verdict_month", "current_price", "level_price"} for r in out
    )
    by = {r["symbol"]: r for r in out}
    assert (
        by["CCC"]["level_price"] == 145.0
        and by["DDD"]["level_price"] is None
        and by["EEE"]["level_price"] is None
    )


def _portfolio_con_posiciones(db_session, tickers, *, colgada=False):
    portfolio = Portfolio(name="Main", base_currency="USD", is_default=True, tenant_id=1)
    db_session.add(portfolio)
    db_session.commit()
    ids = []
    for t in tickers:
        company = Company(
            ticker=t,
            name=t,
            exchange="NASDAQ",
            currency="USD",
            company_type="operating",
            valuation_model="dcf",
        )
        db_session.add(company)
        db_session.commit()
        ids.append(company.id)
    if colgada:
        ids.append(999999)  # empresa inexistente: position.company es None
    for cid in ids:
        db_session.add(
            Position(
                portfolio_id=portfolio.id,
                company_id=cid,
                quantity=Decimal("1"),
                market_price=Decimal("1"),
                currency="USD",
                as_of=HOY,
                tenant_id=1,
            )
        )
    db_session.commit()
    return portfolio


def test_portfolio_sin_posiciones(db_session, monkeypatch):
    portfolio = Portfolio(name="Main", base_currency="USD", is_default=True, tenant_id=1)
    db_session.add(portfolio)
    db_session.commit()
    monkeypatch.setattr(pfx.PortfolioFXService, "ensure_portfolio", lambda self, db: portfolio)
    assert CachedDcaScheduleService().get_portfolio_dca_signals(db_session) == []


def test_portfolio_excluye_posicion_sin_empresa_y_payload_sin_verdict(db_session, monkeypatch):
    portfolio = _portfolio_con_posiciones(db_session, ["AAA", "BBB", "CCC", "DDD"], colgada=True)
    db_session.add_all(
        [
            _signal("AAA", 4, level_prices={"4": "145.00"}),  # feliz: float() se ejecuta
            _signal("BBB", 1, level_prices={}),  # dict vacío: ni se consulta el nivel
            _signal("CCC", 2, level_prices={"2": "caro"}),  # valor no convertible -> None
            _signal("DDD", 3),  # nivel 3 ausente del dict {"2": ...}
        ]
    )
    db_session.commit()
    monkeypatch.setattr(pfx.PortfolioFXService, "ensure_portfolio", lambda self, db: portfolio)
    out = CachedDcaScheduleService().get_portfolio_dca_signals(db_session)
    assert [r["symbol"] for r in out] == ["AAA", "DDD", "CCC", "BBB"]  # nivel descendente
    by = {r["symbol"]: r for r in out}
    assert set(by["AAA"]) == {"symbol", "current_level", "current_price", "level_price"}  # sin verdict_month
    assert by["AAA"]["level_price"] == 145.0
    assert (
        by["BBB"]["level_price"] is None
        and by["CCC"]["level_price"] is None
        and by["DDD"]["level_price"] is None
    )


def test_invalidate_cache_fuerza_miss(db_session):
    db_session.add(_signal("AAA"))
    db_session.commit()
    service = CachedDcaScheduleService()
    with _stats_aisladas():
        reset_cache_stats()
        service.get_dca_signals(db_session)
        service.get_dca_signals(db_session)
        stats = get_cache_stats()["dca_schedule"]
        assert (stats["misses"], stats["hits"]) == (1, 1)
        service.invalidate_cache(db_session)
        service.get_dca_signals(db_session)
        stats = get_cache_stats()["dca_schedule"]
        assert (stats["misses"], stats["hits"]) == (2, 1)
