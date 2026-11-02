"""DCA al añadir: encolar la evaluación de lo recién seguido (una vez por
ticker, solo lo debido, por tenant) sin romper nunca el alta."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import DcaSignalState, WatchItem
from app.models.entities import Base
from app.services import dca_on_add
from app.services.dca_signal_engine import DEFAULT_PARAMS


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.closed = False

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def delete(self, key):
        self.data.pop(key, None)

    def exists(self, key):
        return int(key in self.data)

    def close(self):
        self.closed = True


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(dca_on_add, "get_settings", lambda: SimpleNamespace(dca_evaluation_enabled=True))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.info["tenant_id"] = 1
        session.info["user_id"] = "u1"
        yield session
    engine.dispose()


def _watch(db, tenant, *symbols):
    own = db.info["tenant_id"]
    db.info["tenant_id"] = tenant  # la guarda de escritura impide filas de otro tenant
    for symbol in symbols:
        db.add(WatchItem(tenant_id=tenant, symbol=symbol))
    db.commit()
    db.info["tenant_id"] = own


def _state(db, tenant, symbol, *, age=timedelta(hours=1), version=DEFAULT_PARAMS.version):
    db.add(DcaSignalState(
        tenant_id=tenant, symbol=symbol, level=1, status="ok", period="2026-10",
        signal_date=date(2026, 10, 30), close=Decimal("1"), params_version=version,
        evaluated_at=datetime.now(UTC) - age, data_source="yahoo"))
    db.commit()


def _capture():
    sent: list[tuple[int, str, list[str]]] = []
    return sent, lambda tenant, user, symbols: sent.append((tenant, user, list(symbols)))


def test_encola_una_vez_lo_recien_seguido_y_sin_senal(db):
    _watch(db, 1, "AAA")
    redis, (sent, sender) = FakeRedis(), _capture()
    assert dca_on_add.enqueue_dca_on_add(db, ["aaa"], client=redis, sender=sender) == 1
    assert sent == [(1, "u1", ["AAA"])]
    assert dca_on_add.is_preparing(db, "AAA", client=redis)
    # Segundo alta (doble clic, importación que repite el ticker): no se re-encola.
    assert dca_on_add.enqueue_dca_on_add(db, ["AAA"], client=redis, sender=sender) == 0
    assert len(sent) == 1


def test_no_encola_lo_fresco_ni_lo_no_seguido(db):
    _watch(db, 1, "FRESH", "OLD", "VER")
    _state(db, 1, "FRESH")
    _state(db, 1, "OLD", age=timedelta(hours=30))
    _state(db, 1, "VER", version="v-vieja")
    redis, (sent, sender) = FakeRedis(), _capture()
    dca_on_add.enqueue_dca_on_add(db, ["FRESH", "OLD", "VER", "NOTRACKED"], client=redis, sender=sender)
    assert sent == [(1, "u1", ["OLD", "VER"])]
    assert not dca_on_add.is_preparing(db, "FRESH", client=redis)


def test_importacion_grande_va_en_lotes_de_diez(db):
    symbols = [f"T{i:02d}" for i in range(23)]
    _watch(db, 1, *symbols)
    redis, (sent, sender) = FakeRedis(), _capture()
    assert dca_on_add.enqueue_dca_on_add(db, symbols, client=redis, sender=sender) == 3
    assert [len(batch) for _, _, batch in sent] == [10, 10, 3]


def test_otro_tenant_no_ve_ni_encola_lo_ajeno(db):
    _watch(db, 2, "AJENO")
    redis, (sent, sender) = FakeRedis(), _capture()
    assert dca_on_add.enqueue_dca_on_add(db, ["AJENO"], client=redis, sender=sender) == 0
    assert sent == []
    redis.set(dca_on_add.mark_key(2, "AJENO"), "queued")
    assert not dca_on_add.is_preparing(db, "AJENO", client=redis)


def test_sin_tenant_o_con_la_evaluacion_apagada_no_encola(db, monkeypatch):
    _watch(db, 1, "AAA")
    redis, (sent, sender) = FakeRedis(), _capture()
    db.info["user_id"] = None
    assert dca_on_add.enqueue_dca_on_add(db, ["AAA"], client=redis, sender=sender) == 0
    db.info["user_id"] = "u1"
    monkeypatch.setattr(dca_on_add, "get_settings", lambda: SimpleNamespace(dca_evaluation_enabled=False))
    assert dca_on_add.enqueue_dca_on_add(db, ["AAA"], client=redis, sender=sender) == 0
    assert sent == []


def test_fallo_de_la_cola_no_rompe_y_libera_la_marca(db):
    _watch(db, 1, "AAA")
    redis = FakeRedis()

    def broken(*_):
        raise ConnectionError("broker caído")

    assert dca_on_add.enqueue_dca_on_add(db, ["AAA"], client=redis, sender=broken) == 0
    assert not dca_on_add.is_preparing(db, "AAA", client=redis)

    class DeadRedis(FakeRedis):
        def set(self, *a, **k):
            raise ConnectionError("redis caído")

        def exists(self, key):
            raise ConnectionError("redis caído")

    assert dca_on_add.enqueue_dca_on_add(db, ["AAA"], client=DeadRedis(), sender=broken) == 0
    assert dca_on_add.is_preparing(db, "AAA", client=DeadRedis()) is False


def test_el_job_evalua_solo_lo_debido_y_borra_las_marcas(db, monkeypatch):
    _watch(db, 1, "AAA", "FRESH")
    _state(db, 1, "FRESH")
    redis = FakeRedis()
    for symbol in ("AAA", "FRESH"):
        redis.set(dca_on_add.mark_key(1, symbol), "queued")
    calls = []

    def evaluate(session, *, symbols):
        calls.append(symbols)
        return {"evaluated": len(symbols)}

    monkeypatch.setattr("app.services.dca_signal_service.evaluate_watchlist", evaluate)
    result = dca_on_add.run_on_add(db, ["AAA", "FRESH"], client=redis)
    assert result["status"] == "ok" and calls == [{"AAA"}]
    assert redis.data == {}
    # Todo al día (lo evaluó el diario entre medias): no se descarga nada.
    redis.set(dca_on_add.mark_key(1, "FRESH"), "queued")
    assert dca_on_add.run_on_add(db, ["FRESH"], client=redis)["status"] == "skipped"
    assert calls == [{"AAA"}] and redis.data == {}


def test_actor_reutiliza_la_cola_dca_manual_y_reintenta_si_el_lease_esta_ocupado(monkeypatch):
    from app.workers import dramatiq_app

    actor = dramatiq_app.evaluate_dca_on_add
    assert actor.queue_name == "dca-manual"
    assert actor.options["max_retries"] == 3
    assert actor.options["min_backoff"] >= 60_000
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda *a, **k: None)
    with pytest.raises(dramatiq_app.DcaOnAddLeaseHeld):
        actor.fn(1, "u1", ["AAA"])


def test_importacion_solo_encola_lo_nunca_evaluado(db):
    _watch(db, 1, "NUEVO", "VIEJO")
    _state(db, 1, "VIEJO", age=timedelta(hours=30))  # lo refresca el diario, no la importación
    redis, (sent, sender) = FakeRedis(), _capture()
    dca_on_add.enqueue_dca_on_add(db, ["NUEVO", "VIEJO"], client=redis, sender=sender, only_new=True)
    assert sent == [(1, "u1", ["NUEVO"])]


def test_tras_importar_encola_lo_seguido_sin_senal(db, monkeypatch):
    _watch(db, 1, "NUEVO", "FRESH")
    _state(db, 1, "FRESH", age=timedelta(hours=30))
    _watch(db, 2, "AJENO")
    calls = []
    monkeypatch.setattr(dca_on_add, "enqueue_dca_on_add", lambda session, symbols, **kw: calls.append((sorted(symbols), kw)) or 1)
    assert dca_on_add.enqueue_dca_for_new_tracked(db) == 1
    assert calls == [(["FRESH", "NUEVO"], {"only_new": True})]
