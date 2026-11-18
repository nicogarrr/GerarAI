"""Pruebas del watchdog de conexiones Postgres (alerta in-app al operador).

Nace del 503 medido en prod el 15-nov-2026 (pool 20+10 agotado sin aviso).
Expected Behavior:
- Una muestra con sesiones 'idle in transaction' viejas, consultas activas
  viejas o saturacion de max_connections genera una ResearchAlert in-app con
  lo medido (conteos, edades, techo); nunca se inventa causa
- Idempotente por tenant, condicion y dia; sin condicion no hay alerta
- Fuera de Postgres o con pg_stat_activity ilegible el tick es skipped,
  nunca una falsa alarma
- El actor libera el lease y cierra la sesion en ok, lease_held y error

Run from data-engine/:
    pytest tests/test_db_connection_watchdog.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import ResearchAlert, Tenant
from app.models.entities import Base
from app.services import db_connection_watchdog as wd
from app.workers import dramatiq_app as worker

NOW = datetime(2026, 11, 18, 6, 30, tzinfo=UTC)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="owner"))
        session.commit()
        session.info.update(tenant_id=1, user_id="owner")
        yield session
    engine.dispose()


def _sample(**over):
    base = {
        "active": 1,
        "idle": 5,
        "idle_in_tx": 0,
        "total": 6,
        "oldest_active_s": 3.0,
        "oldest_idle_tx_s": 0.0,
        "max_connections": 100,
    }
    base.update(over)
    return base


# --- umbrales por entorno ---------------------------------------------------


def test_umbrales_por_defecto(monkeypatch):
    for var in ("DB_WATCHDOG_IDLE_TX_SECONDS", "DB_WATCHDOG_ACTIVE_QUERY_SECONDS",
                "DB_WATCHDOG_SATURATION_PCT", "DB_WATCHDOG_QUERY_TIMEOUT_MS"):
        monkeypatch.delenv(var, raising=False)
    assert wd.idle_tx_threshold_seconds() == 300.0
    assert wd.active_query_threshold_seconds() == 900.0
    assert wd.saturation_pct_threshold() == 80.0
    assert wd.query_timeout_ms() == 10000


def test_umbrales_invalidos_caen_al_defecto(monkeypatch):
    monkeypatch.setenv("DB_WATCHDOG_IDLE_TX_SECONDS", "no-numero")
    monkeypatch.setenv("DB_WATCHDOG_ACTIVE_QUERY_SECONDS", "x")
    monkeypatch.setenv("DB_WATCHDOG_SATURATION_PCT", "abc")
    assert wd.idle_tx_threshold_seconds() == 300.0
    assert wd.active_query_threshold_seconds() == 900.0
    assert wd.saturation_pct_threshold() == 80.0


def test_umbrales_tienen_piso_y_techo(monkeypatch):
    monkeypatch.setenv("DB_WATCHDOG_IDLE_TX_SECONDS", "1")
    monkeypatch.setenv("DB_WATCHDOG_ACTIVE_QUERY_SECONDS", "5")
    monkeypatch.setenv("DB_WATCHDOG_SATURATION_PCT", "250")
    assert wd.idle_tx_threshold_seconds() == 30.0
    assert wd.active_query_threshold_seconds() == 60.0
    assert wd.saturation_pct_threshold() == 100.0


# --- sample_connections -----------------------------------------------------


def test_timeout_invalido_cae_al_defecto_y_con_piso(monkeypatch):
    monkeypatch.setenv("DB_WATCHDOG_QUERY_TIMEOUT_MS", "no-numero")
    assert wd.query_timeout_ms() == 10000
    monkeypatch.setenv("DB_WATCHDOG_QUERY_TIMEOUT_MS", "10")
    assert wd.query_timeout_ms() == 1000  # piso


def test_sample_sqlite_es_skipped(db):
    assert wd.sample_connections(db) is None


def test_sample_postgres_parsea_la_fila():
    """Un bind falso postgres ejercita el SQL y el parseo sin servidor real."""
    executed: list[tuple[str, dict]] = []

    class _Result:
        def __init__(self, row=None, scalar=None):
            self._row = row
            self._scalar = scalar

        def one(self):
            return self._row

        def scalar_one(self):
            return self._scalar

    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    class _FakeDb:
        def get_bind(self):
            return bind

        def execute(self, clause, params=None):
            sql = str(clause)
            executed.append((sql, params or {}))
            if "pg_stat_activity" in sql:
                return _Result(row=SimpleNamespace(
                    active=2, idle=4, idle_in_tx=1, total=7,
                    oldest_active_s=12.5, oldest_idle_tx_s=400.0,
                ))
            if "pg_settings" in sql:
                return _Result(scalar=100)
            return _Result()  # set_config

    sample = wd.sample_connections(_FakeDb())

    assert sample == {
        "active": 2, "idle": 4, "idle_in_tx": 1, "total": 7,
        "oldest_active_s": 12.5, "oldest_idle_tx_s": 400.0,
        "max_connections": 100,
    }
    assert len(executed) == 3
    assert "pg_backend_pid" in executed[1][0]  # la propia sesion queda excluida


def test_timeout_explicito_antes_de_leer(monkeypatch):
    """v2: statement_timeout y lock_timeout acotados antes de las lecturas.

    Sin el, una lectura bloqueada podia superar el lease de 120 s del actor
    y ocupar la cola de alertas (repro del auditor).
    """
    monkeypatch.setenv("DB_WATCHDOG_QUERY_TIMEOUT_MS", "4000")
    calls: list[tuple[str, dict]] = []
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    class _FakeDb:
        def get_bind(self):
            return bind

        def execute(self, clause, params=None):
            sql = str(clause)
            calls.append((sql, params or {}))
            if "pg_stat_activity" in sql:
                return SimpleNamespace(one=lambda: SimpleNamespace(
                    active=0, idle=0, idle_in_tx=0, total=0,
                    oldest_active_s=0.0, oldest_idle_tx_s=0.0))
            return SimpleNamespace(scalar_one=lambda: 100)

    wd.sample_connections(_FakeDb())

    first_sql, first_params = calls[0]
    assert "set_config" in first_sql
    assert "statement_timeout" in first_sql and "lock_timeout" in first_sql
    assert "is_local" in first_sql or "true" in first_sql  # local a la transaccion
    assert first_params.get("ms") == "4000"


def test_edad_idle_se_mide_por_state_change_no_xact_start():
    """v2: la edad idle es la del ESTADO (state_change), no la transaccion.

    Con xact_start, una consulta legitima de >300 s que acababa de terminar
    disparaba una falsa alerta de 'idle' (reproducido en PG14 real por el
    auditor: consulta de 0,8 s publicaba edad idle 0,806 s siendo 0,011 s).
    """
    sql_capturado: list[str] = []
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    class _FakeDb:
        def get_bind(self):
            return bind

        def execute(self, clause, params=None):
            sql = str(clause)
            if "pg_stat_activity" in sql:
                sql_capturado.append(sql)
                return SimpleNamespace(one=lambda: SimpleNamespace(
                    active=0, idle=0, idle_in_tx=0, total=0,
                    oldest_active_s=0.0, oldest_idle_tx_s=0.0))
            return SimpleNamespace(scalar_one=lambda: 100)

    wd.sample_connections(_FakeDb())

    (sample_sql,) = sql_capturado
    assert "now() - state_change" in sample_sql
    assert "now() - xact_start" not in sample_sql
    assert "now() - query_start" in sample_sql  # la edad activa sigue por query_start


def test_conteo_y_edades_son_del_servidor_completo():
    """v2: sin filtro por base; max_connections es un techo GLOBAL.

    Contar solo la base actual ocultaba la saturacion si otra base agotaba
    el servidor (repro del auditor: el mensaje decia 'conexiones del
    servidor' pero contaba una sola base).
    """
    import inspect

    fuente = inspect.getsource(wd.sample_connections)
    assert "datname" not in fuente

    sql_capturado: list[str] = []
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    class _FakeDb:
        def get_bind(self):
            return bind

        def execute(self, clause, params=None):
            sql = str(clause)
            if "pg_stat_activity" in sql:
                sql_capturado.append(sql)
                return SimpleNamespace(one=lambda: SimpleNamespace(
                    active=0, idle=0, idle_in_tx=0, total=0,
                    oldest_active_s=0.0, oldest_idle_tx_s=0.0))
            return SimpleNamespace(scalar_one=lambda: 100)

    wd.sample_connections(_FakeDb())

    (sample_sql,) = sql_capturado
    assert "datname" not in sample_sql


def test_sample_error_de_lectura_es_skipped_no_alarma():
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    class _FakeDb:
        def get_bind(self):
            return bind

        def execute(self, clause):
            raise PermissionError("sin permiso para pg_stat_activity")

    assert wd.sample_connections(_FakeDb()) is None


# --- detect_issues (puro) ---------------------------------------------------


def test_muestra_sana_no_genera_issues():
    assert wd.detect_issues(_sample()) == []


def test_idle_in_transaction_viejo_genera_issue():
    issues = wd.detect_issues(
        _sample(idle_in_tx=2, oldest_idle_tx_s=400.0), idle_tx_s=300.0
    )
    assert [i["kind"] for i in issues] == ["idle_in_transaction"]
    assert issues[0]["severity"] == "medium"
    assert issues[0]["count"] == 2
    assert issues[0]["oldest_s"] == 400.0


def test_idle_in_transaction_justo_en_el_umbral_alerta_y_debajo_no():
    assert wd.detect_issues(
        _sample(idle_in_tx=1, oldest_idle_tx_s=300.0), idle_tx_s=300.0
    )[0]["kind"] == "idle_in_transaction"
    assert wd.detect_issues(
        _sample(idle_in_tx=1, oldest_idle_tx_s=299.9), idle_tx_s=300.0
    ) == []


def test_consulta_activa_vieja_genera_issue():
    issues = wd.detect_issues(
        _sample(active=3, oldest_active_s=1000.0), active_s=900.0
    )
    assert [i["kind"] for i in issues] == ["active_query"]
    assert issues[0]["count"] == 3


def test_saturacion_genera_issue_high():
    issues = wd.detect_issues(
        _sample(total=85, max_connections=100), saturation_pct=80.0
    )
    assert [i["kind"] for i in issues] == ["saturation"]
    assert issues[0]["severity"] == "high"
    assert issues[0]["pct"] == 85.0


def test_saturacion_debajo_del_umbral_no_alerta():
    assert wd.detect_issues(_sample(total=79, max_connections=100), saturation_pct=80.0) == []


def test_max_connections_cero_no_divide():
    assert wd.detect_issues(_sample(total=10, max_connections=0), saturation_pct=80.0) == []


def test_varias_condiciones_a_la_vez():
    issues = wd.detect_issues(
        _sample(idle_in_tx=1, oldest_idle_tx_s=600.0, active=2,
                oldest_active_s=2000.0, total=95, max_connections=100),
        idle_tx_s=300.0, active_s=900.0, saturation_pct=80.0,
    )
    assert [i["kind"] for i in issues] == [
        "idle_in_transaction", "active_query", "saturation",
    ]


# --- emit_db_connection_alerts ----------------------------------------------


def test_emit_crea_alerta_con_lo_medido(db):
    out = wd.emit_db_connection_alerts(
        db, now=NOW, sampler=lambda: _sample(idle_in_tx=2, oldest_idle_tx_s=400.0)
    )

    assert out["status"] == "ok"
    assert out["created"] == 1 and out["issues"] == 1
    alert = db.scalar(select(ResearchAlert))
    assert alert.alert_type == "db_connection"
    assert alert.severity == "medium"
    assert alert.channels == ["in_app"]
    assert "2 sesiones" in alert.message
    assert "400 s" in alert.message
    assert "idle in transaction" in alert.message
    # Veracidad: la causa se declara posible, nunca afirmada.
    assert "Causa posible" in alert.message
    assert alert.metadata_["kind"] == "idle_in_transaction"
    assert alert.metadata_["sample"]["oldest_idle_tx_s"] == 400.0


def test_emit_es_idempotente_por_dia(db):
    sampler = lambda: _sample(total=90, max_connections=100)  # noqa: E731
    first = wd.emit_db_connection_alerts(db, now=NOW, sampler=sampler)
    second = wd.emit_db_connection_alerts(db, now=NOW, sampler=sampler)

    assert first["created"] == 1
    assert second["created"] == 0 and second["existing"] == 1
    assert db.scalars(select(ResearchAlert)).all().__len__() == 1


def test_emit_otro_dia_permite_nueva_alerta(db):
    sampler = lambda: _sample(total=90, max_connections=100)  # noqa: E731
    wd.emit_db_connection_alerts(db, now=NOW, sampler=sampler)
    later = datetime(2026, 11, 19, 6, 30, tzinfo=UTC)
    out = wd.emit_db_connection_alerts(db, now=later, sampler=sampler)
    assert out["created"] == 1


def test_emit_muestra_sana_no_crea_nada(db):
    out = wd.emit_db_connection_alerts(db, now=NOW, sampler=lambda: _sample())
    assert out["status"] == "ok" and out["created"] == 0 and out["issues"] == 0
    assert db.scalar(select(ResearchAlert)) is None


def test_emit_muestra_ilegible_es_skipped(db):
    out = wd.emit_db_connection_alerts(db, now=NOW, sampler=lambda: None)
    assert out == {"status": "skipped", "reason": "sample_unavailable", "issues": 0}
    assert db.scalar(select(ResearchAlert)) is None


def test_emit_sin_tenant_es_error(db):
    db.info.clear()
    with pytest.raises(ValueError, match="Tenant context required"):
        wd.emit_db_connection_alerts(db, now=NOW, sampler=lambda: _sample())


def test_mensaje_saturacion_recoge_el_techo(db):
    wd.emit_db_connection_alerts(
        db, now=NOW, sampler=lambda: _sample(total=85, max_connections=100)
    )
    alert = db.scalar(select(ResearchAlert))
    assert alert.severity == "high"
    assert "85/100" in alert.message
    assert "85.0%" in alert.message


def test_mensaje_consulta_activa_recoge_la_edad(db):
    wd.emit_db_connection_alerts(
        db, now=NOW, sampler=lambda: _sample(active=3, oldest_active_s=1000.0)
    )
    alert = db.scalar(select(ResearchAlert))
    assert "3 consultas activas" in alert.message
    assert "1000 s" in alert.message


# --- actor dispatch_db_connection_watchdog ----------------------------------


@pytest.fixture()
def env(monkeypatch):
    """Sesion/lease/rollback falsos; el actor no toca Redis ni Postgres."""
    e = SimpleNamespace(
        db=MagicMock(),
        lease="LEASE",
        released=[],
        acquired=[],
        rolled=[],
        handled=[],
    )
    monkeypatch.setattr(worker, "_session", lambda tenant, user: e.db)

    def acquire(key, **kw):
        e.acquired.append((key, kw["ttl_seconds"]))
        return e.lease

    def handle(actor, exc, **ctx):
        e.handled.append((actor, exc, ctx))
        return {"status": "error", "actor": actor, "error": {"type": type(exc).__name__}}

    monkeypatch.setattr(worker, "acquire_job_lease", acquire)
    monkeypatch.setattr(worker, "release_job_lease", lambda key, lease, **kw: e.released.append((key, lease)))
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))
    monkeypatch.setattr(worker, "_handle_actor_error", handle)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    return e


def test_actor_ok_libera_lease_y_cierra(env, monkeypatch):
    seen = {}

    def emit(db):
        seen["db"] = db
        return {"created": 1}

    monkeypatch.setattr(wd, "emit_db_connection_alerts", emit)

    out = worker.dispatch_db_connection_watchdog.fn(tenant_id=1, user_id="u")

    assert out == {"status": "ok", "actor": "dispatch_db_connection_watchdog", "created": 1}
    assert seen["db"] is env.db
    assert env.acquired == [("dispatch_db_connection_watchdog:1", 120)]
    assert env.released == [("dispatch_db_connection_watchdog:1", "LEASE")]
    env.db.close.assert_called_once_with()


def test_actor_lease_held_no_trabaja(env, monkeypatch):
    env.lease = None
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: None)
    called = []
    monkeypatch.setattr(wd, "emit_db_connection_alerts", lambda db: called.append(db))

    out = worker.dispatch_db_connection_watchdog.fn(tenant_id=1, user_id="u")

    assert out == {"status": "skipped", "actor": "dispatch_db_connection_watchdog",
                   "reason": "lease_held"}
    assert called == []
    env.db.close.assert_called_once_with()


def test_actor_error_rollback_lease_y_cierre(env, monkeypatch):
    boom = KeyError("pg_stat_activity")

    def fail(db):
        raise boom

    monkeypatch.setattr(wd, "emit_db_connection_alerts", fail)

    out = worker.dispatch_db_connection_watchdog.fn(tenant_id=1, user_id="u")

    assert out["status"] == "error"
    assert env.handled and env.handled[0][1] is boom
    assert env.rolled == [env.db]
    assert env.released == [("dispatch_db_connection_watchdog:1", "LEASE")]
    env.db.close.assert_called_once_with()


def test_actor_en_taxonomia_mantenimiento():
    from app.workers.queue_taxonomy import ACTOR_CLASS, MANTENIMIENTO

    assert ACTOR_CLASS["dispatch_db_connection_watchdog"] == MANTENIMIENTO
