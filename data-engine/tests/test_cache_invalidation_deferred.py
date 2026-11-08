"""Invalidacion diferida de cache por eventos ORM (app/core/cache_invalidation.py).

Hueco de cobertura: el modulo no tenia ningun test. El contrato que se fija
aqui:

- ``after_flush`` solo ACUMULA (no toca Redis antes del commit, para que nadie
  recachee el dato viejo entre flush y commit);
- ``after_commit`` aplica las invalidaciones por tenant: cartera para
  Transaction/CashBalance/Portfolio/FxConversion/Position, DCA para
  DcaSignalState/DcaAlertOverride/DcaAlertSettings/WatchItem, y AMBAS para
  Position (alimenta las dos respuestas);
- ``after_rollback`` descarta lo acumulado;
- un fallo de Redis al invalidar NO rompe el commit;
- el DML bulk no pasa por session.new/dirty/deleted: NO invalida (limitacion
  documentada; esos flujos invalidan a mano en el servicio o la ruta).

Los listeners reales se instalan al importar app.models; para observarlos sin
Redis se sustituye ``app.core.cache._redis_client`` por un cliente falso que
registra los patrones de borrado. Es un test de extremo a extremo del flujo
ORM -> cache, no de una re-instalacion de listeners.
"""

from __future__ import annotations

import fnmatch
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

import app.core.cache as cache_module
import app.models  # noqa: F401  (registra tablas e instala los listeners reales)
from app.models import Company, Position, Tenant, Transaction, WatchItem
from app.models.entities import Base


class FakeRedis:
    """Redis en memoria: registra patrones de scan y claves borradas."""

    def __init__(self) -> None:
        self.store: set[str] = set()
        self.scan_patterns: list[str] = []
        self.deleted: list[str] = []

    def scan(self, cursor: int, match: str, count: int):  # noqa: ARG002
        self.scan_patterns.append(match)
        matched = sorted(k for k in self.store if fnmatch.fnmatchcase(k, match))
        return (0, matched)

    def delete(self, *keys: str) -> int:
        for key in keys:
            self.store.discard(key)
            self.deleted.append(key)
        return len(keys)


@pytest.fixture()
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(cache_module, "_redis_client", lambda: fake)
    return fake


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _tenant(db: Session) -> Tenant:
    tenant = Tenant(external_id="ci-tenant", name="CI")
    db.add(tenant)
    db.commit()
    return tenant


def test_flush_only_accumulates_commit_applies(db, fake_redis):
    tenant = _tenant(db)
    db.add(
        Transaction(
            tenant_id=tenant.id,
            action="buy",
            quantity=Decimal("1"),
            price=Decimal("10"),
            trade_date=date(2024, 1, 1),
        )
    )
    db.flush()
    # Entre flush y commit no se toca Redis: otro request recachearia el dato viejo.
    assert fake_redis.scan_patterns == []
    db.commit()
    assert fake_redis.scan_patterns == [
        f"portfolio_valuation*:tenant:{tenant.id}:*"
    ]


def test_commit_deletes_only_the_tenant_keys(db, fake_redis):
    tenant = _tenant(db)
    own = f"portfolio_valuation:summary:tenant:{tenant.id}:hash1"
    other = "portfolio_valuation:summary:tenant:999:hash2"
    fake_redis.store.update({own, other})
    db.add(WatchItem(tenant_id=tenant.id, symbol="AAPL", company="Apple"))
    db.commit()
    # La cartera del tenant NO se toca (WatchItem solo invalida DCA) y la del
    # tenant 999 tampoco: la invalidacion DCA lleva su propio patron por tenant.
    assert other in fake_redis.store
    assert fake_redis.scan_patterns == [f"dca_schedule*:tenant:{tenant.id}:*"]


def test_position_invalidates_portfolio_and_dca(db, fake_redis):
    tenant = _tenant(db)
    company = Company(
        ticker="PCI", name="Pos CI", exchange="NYSE", currency="USD",
        company_type="research_candidate", valuation_model="unassigned",
    )
    db.add(company)
    db.flush()
    db.add(Position(tenant_id=tenant.id, company_id=company.id, quantity=1, base_currency="EUR"))
    db.commit()
    assert sorted(fake_redis.scan_patterns) == sorted(
        [
            f"portfolio_valuation*:tenant:{tenant.id}:*",
            f"dca_schedule*:tenant:{tenant.id}:*",
        ]
    )


def test_rollback_discards_pending_invalidation(db, fake_redis):
    tenant = _tenant(db)
    db.add(WatchItem(tenant_id=tenant.id, symbol="MSFT", company="Microsoft"))
    db.flush()
    db.rollback()
    assert fake_redis.scan_patterns == []


def test_unrelated_model_does_not_invalidate(db, fake_redis):
    _tenant(db)  # Tenant no es un modelo cacheado: ni cartera ni DCA
    assert fake_redis.scan_patterns == []


def test_redis_failure_does_not_break_commit(db, monkeypatch):
    class FailingRedis:
        def scan(self, cursor, match, count):
            raise ConnectionError("redis caido")

    monkeypatch.setattr(cache_module, "_redis_client", lambda: FailingRedis())
    tenant = _tenant(db)
    db.add(WatchItem(tenant_id=tenant.id, symbol="TSLA", company="Tesla"))
    db.commit()  # no debe lanzar: la invalidacion es best-effort
    assert db.scalar(select(WatchItem).where(WatchItem.symbol == "TSLA")) is not None


def test_bulk_dml_does_not_invalidate_documented_gap(db, fake_redis):
    """El DML bulk no puebla session.new/dirty/deleted: no hay invalidacion.

    Es la limitacion documentada del modulo: los flujos bulk (market refresh,
    PATCH de precios, evaluate DCA) mantienen su invalidacion explicita
    post-commit. Este test fija ese contrato para que nadie "arregle" el
    evento creyendo que cubre el bulk.
    """
    tenant = _tenant(db)
    db.add(WatchItem(tenant_id=tenant.id, symbol="TSLA", company="Tesla"))
    db.commit()
    fake_redis.scan_patterns.clear()

    db.execute(delete(WatchItem).where(WatchItem.symbol == "TSLA"))
    db.commit()
    assert fake_redis.scan_patterns == []


def test_invalidation_listeners_installed_once():
    """El modulo se instala al importar app.models y no se duplica."""
    import app.core.cache_invalidation as cache_invalidation

    assert cache_invalidation._installed is True
    cache_invalidation.install_invalidation_listeners()  # no-op idempotente
    assert cache_invalidation._installed is True
