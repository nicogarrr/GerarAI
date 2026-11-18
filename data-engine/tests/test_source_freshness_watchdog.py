"""Pruebas del watchdog de frescura de fuentes (alerta in-app al operador).

Nace del incidente medido el 1-nov-2026: FMP y yahoo_intraday llevaban paradas
desde el 2/7 de octubre y nadie lo vio (el panel lo marca, pero es pull).
Expected Behavior:
- Una fuente que ENTRA en stale genera una ResearchAlert in-app con lo medido
  (capa, fuente, ultima escritura, limite de edad); nunca afirma la causa
- Dedup durable por episodio: una fuente que sigue stale (reinicio o cambio
  de dia) no realerta; al recuperarse se persiste el cierre (alerta info) y
  un nuevo stale vuelve a alertar; el fingerprint por dia es el respaldo
- Una capa con status=error es "no medido" visible: tick skipped, nunca ok
- Inventario ilegible = skipped, nunca una falsa alarma
- El actor libera el lease y cierra la sesion en ok, lease_held y error

Run from data-engine/:
    pytest tests/test_source_freshness_watchdog.py -v
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import ResearchAlert, Tenant
from app.models.entities import Base
from app.services import source_freshness_watchdog as wd
from app.workers import dramatiq_app as worker

NOW = datetime(2026, 11, 18, 7, 0, tzinfo=UTC)


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


def _fila(status: str, *, layer: str = "Precios diarios", source: str = "fmp",
          last_update: str | None = "2026-10-02T00:00:00+00:00", max_age: int = 4) -> dict:
    return {"layer": layer, "source": source, "covered": 10, "total": 100,
            "coverage_pct": 10.0, "eligible": None, "coverage_pct_eligible": None,
            "last_update": last_update, "status": status,
            "max_age_days": max_age, "reason": None}


def _inventario(*filas: dict) -> dict:
    return {"as_of": NOW.isoformat(), "total_companies": 100,
            "sources": list(filas), "connectors": []}


# --- detect_stale (puro) ----------------------------------------------------


def test_fuente_sana_no_alertable():
    assert wd.detect_stale([_fila("available")], last_states={}) == []


def test_fuente_stale_nueva_alerta():
    stale = wd.detect_stale([_fila("stale")], last_states={})
    assert len(stale) == 1
    assert stale[0]["previous_status"] is None


def test_fuente_que_sigue_stale_no_realerta():
    estados = {("Precios diarios", "fmp"): "stale"}
    assert wd.detect_stale([_fila("stale")], last_states=estados) == []


def test_fuente_recuperada_y_caida_vuelve_a_alertar():
    estados = {("Precios diarios", "fmp"): "available"}
    stale = wd.detect_stale([_fila("stale")], last_states=estados)
    assert len(stale) == 1
    assert stale[0]["previous_status"] == "available"


def test_capas_distintas_son_fuentes_distintas():
    estados = {("Noticias", "fmp"): "stale"}
    stale = wd.detect_stale([_fila("stale")], last_states=estados)
    assert len(stale) == 1  # misma fuente, otra capa: alerta aparte


def test_record_states_graba_tras_commit():
    estados: dict = {}
    wd.record_states([_fila("stale")], last_states=estados)
    assert estados == {("Precios diarios", "fmp"): "stale"}


# --- emit_source_freshness_alerts -------------------------------------------


def test_emit_crea_alerta_con_lo_medido(db):
    out = wd.emit_source_freshness_alerts(
        db, now=NOW, inventory_provider=lambda: _inventario(_fila("stale")),
        last_states={},
    )
    assert out["status"] == "ok" and out["created"] == 1 and out["stale"] == 1
    alert = db.scalar(select(ResearchAlert))
    assert alert.alert_type == "source_freshness"
    assert alert.severity == "high"  # Precios diarios es la capa que mas duele
    assert "fmp" in alert.message
    assert "2026-10-02" in alert.message
    assert "4 dias" in alert.message
    # Veracidad: ultima escritura en BD, nunca proveedor caido.
    assert "ultima escritura medida en la base de datos" in alert.message
    assert "Causa posible" in alert.message
    assert alert.metadata_["layer"] == "Precios diarios"
    assert alert.metadata_["max_age_days"] == 4


def test_emit_capa_no_precios_es_medium(db):
    wd.emit_source_freshness_alerts(
        db, now=NOW,
        inventory_provider=lambda: _inventario(_fila("stale", layer="Noticias", source="gdelt")),
        last_states={},
    )
    assert db.scalar(select(ResearchAlert)).severity == "medium"


def test_emit_idempotente_mismo_dia(db):
    proveedor = lambda: _inventario(_fila("stale"))  # noqa: E731
    estados: dict = {}
    first = wd.emit_source_freshness_alerts(db, now=NOW, inventory_provider=proveedor,
                                            last_states=estados)
    # Segundo tick del mismo proceso: la fuente sigue stale, no realerta.
    second = wd.emit_source_freshness_alerts(db, now=NOW, inventory_provider=proveedor,
                                             last_states=estados)
    assert first["created"] == 1
    assert second["created"] == 0 and second["stale"] == 0
    assert len(db.scalars(select(ResearchAlert)).all()) == 1


def test_emit_reinicio_de_proceso_no_duplica_gracias_al_estado_durable(db):
    proveedor = lambda: _inventario(_fila("stale"))  # noqa: E731
    wd.emit_source_freshness_alerts(db, now=NOW, inventory_provider=proveedor, last_states={})
    # Estados en memoria vacios (worker reiniciado): el episodio durable
    # (historia de alertas) sigue abierto y suprime la realerta.
    out = wd.emit_source_freshness_alerts(db, now=NOW, inventory_provider=proveedor,
                                          last_states={})
    assert out["created"] == 0 and out["stale"] == 0
    assert len(db.scalars(select(ResearchAlert)).all()) == 1


def test_otro_dia_con_el_mismo_episodio_no_realerta(db):
    """v2 (repro del auditor): dedup durable por episodio, no por dia.

    Un reinicio al dia siguiente con la MISMA fuente aun stale no crea otra
    alerta: no hubo recuperacion intermedia.
    """
    proveedor = lambda: _inventario(_fila("stale"))  # noqa: E731
    first = wd.emit_source_freshness_alerts(db, now=NOW, inventory_provider=proveedor,
                                            last_states={})
    assert first["created"] == 1
    later = datetime(2026, 11, 19, 7, 0, tzinfo=UTC)
    out = wd.emit_source_freshness_alerts(db, now=later, inventory_provider=proveedor,
                                          last_states={})
    assert out["created"] == 0 and out["stale"] == 0
    assert len(db.scalars(select(ResearchAlert)).all()) == 1


def test_recuperacion_cierra_episodio_y_un_nuevo_stale_alerta(db):
    """v2: stale -> recovered (alerta info de cierre) -> stale nuevo alerta."""
    later = datetime(2026, 11, 19, 7, 0, tzinfo=UTC)
    latest = datetime(2026, 11, 20, 7, 0, tzinfo=UTC)
    stale = lambda: _inventario(_fila("stale"))  # noqa: E731
    sana = lambda: _inventario(_fila("available"))  # noqa: E731

    first = wd.emit_source_freshness_alerts(db, now=NOW, inventory_provider=stale,
                                            last_states={})
    assert first["created"] == 1

    rec = wd.emit_source_freshness_alerts(db, now=later, inventory_provider=sana,
                                          last_states={})
    assert rec["created"] == 1 and rec["recovered"] == 1
    alerta_rec = db.scalars(
        select(ResearchAlert).order_by(ResearchAlert.id.desc())
    ).first()
    assert alerta_rec.severity == "info" and "recuperada" in alerta_rec.title

    again = wd.emit_source_freshness_alerts(db, now=latest, inventory_provider=stale,
                                            last_states={})
    assert again["created"] == 1 and again["stale"] == 1
    assert len(db.scalars(select(ResearchAlert)).all()) == 3


def test_capa_con_error_es_skipped_visible_no_ok(db):
    """v2 (repro del auditor): status=error de una capa = no medido, nunca ok."""
    inventario = {
        "sources": [{"layer": "Precios diarios", "source": None, "status": "error",
                     "last_update": None, "max_age_days": 4}],
    }
    out = wd.emit_source_freshness_alerts(
        db, now=NOW, inventory_provider=lambda: inventario, last_states={},
    )
    assert out["status"] == "skipped"
    assert out["reason"] == "inventory_layer_error"
    assert out["layers"] == ["Precios diarios"]
    assert db.scalar(select(ResearchAlert)) is None


def test_capa_error_mezclada_con_stale_tambien_es_skipped(db):
    """Una sola capa ilegible invalida el tick entero (no se midio todo)."""
    inventario = _inventario(_fila("stale"),
                             {"layer": "Noticias", "source": None, "status": "error",
                              "last_update": None, "max_age_days": 7})
    out = wd.emit_source_freshness_alerts(
        db, now=NOW, inventory_provider=lambda: inventario, last_states={},
    )
    assert out["status"] == "skipped" and out["reason"] == "inventory_layer_error"
    assert db.scalar(select(ResearchAlert)) is None


def test_timeout_de_lectura_valores(monkeypatch):
    """v3: el timeout por consulta tiene defecto, piso y caida al defecto."""
    monkeypatch.delenv("SOURCE_WATCHDOG_QUERY_TIMEOUT_MS", raising=False)
    assert wd.query_timeout_ms() == 20000
    monkeypatch.setenv("SOURCE_WATCHDOG_QUERY_TIMEOUT_MS", "no-numero")
    assert wd.query_timeout_ms() == 20000
    monkeypatch.setenv("SOURCE_WATCHDOG_QUERY_TIMEOUT_MS", "10")
    assert wd.query_timeout_ms() == 1000  # piso


def test_ruta_real_pasa_el_timeout_al_inventario(db, monkeypatch):
    """v3: inventory() recibe statement_timeout_ms y lo reaplica por capa.

    Aplicarlo una sola vez fuera solo protegia la primera transaccion: el
    rollback interno de una capa descarta el SET LOCAL (medido en PG real:
    SHOW statement_timeout devuelve 0 tras el rollback).
    """
    monkeypatch.setenv("SOURCE_WATCHDOG_QUERY_TIMEOUT_MS", "7000")
    llamadas: list[dict] = {}

    def fake_inventory(db_arg, **kwargs):
        llamadas.update(kwargs)
        return _inventario(_fila("available"))

    import app.services.data_health_service as dhs

    monkeypatch.setattr(dhs, "inventory", fake_inventory)
    out = wd.emit_source_freshness_alerts(db, now=NOW, last_states={})
    assert out["status"] == "ok"
    assert llamadas.get("statement_timeout_ms") == 7000
    assert out["tick_ms"] >= 0


def test_emit_sin_stale_no_crea_nada(db):
    out = wd.emit_source_freshness_alerts(
        db, now=NOW, inventory_provider=lambda: _inventario(_fila("available")),
        last_states={},
    )
    assert out["status"] == "ok" and out["created"] == 0
    assert db.scalar(select(ResearchAlert)) is None


def test_emit_inventario_ilegible_es_skipped(db):
    def falla():
        raise RuntimeError("pg caido")

    out = wd.emit_source_freshness_alerts(db, now=NOW, inventory_provider=falla,
                                          last_states={})
    assert out == {"status": "skipped", "reason": "inventory_unavailable", "stale": 0}
    assert db.scalar(select(ResearchAlert)) is None


def test_emit_sin_tenant_es_error(db):
    db.info.clear()
    with pytest.raises(ValueError, match="Tenant context required"):
        wd.emit_source_freshness_alerts(db, now=NOW,
                                        inventory_provider=lambda: _inventario(),
                                        last_states={})


def test_emit_usa_estado_global_del_proceso(db, monkeypatch):
    # Sin last_states inyectado, la memoria es el dict global del proceso:
    # la segunda pasada del mismo dia no realerta.
    monkeypatch.setattr(wd, "_last_states", {})
    proveedor = lambda: _inventario(_fila("stale"))  # noqa: E731
    first = wd.emit_source_freshness_alerts(db, now=NOW, inventory_provider=proveedor)
    second = wd.emit_source_freshness_alerts(db, now=NOW, inventory_provider=proveedor)
    assert first["created"] == 1 and second["stale"] == 0


def test_emit_sin_provider_usa_el_inventario_real(db):
    # inventory() sobre sqlite recorre la ruta group-by: BD vacia = capas
    # "empty", ninguna stale, ninguna alerta.
    out = wd.emit_source_freshness_alerts(db, now=NOW, last_states={})
    assert out["status"] == "ok" and out["created"] == 0
    assert db.scalar(select(ResearchAlert)) is None


# --- actor dispatch_source_freshness_watchdog -------------------------------


@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(db=MagicMock(), lease="LEASE", released=[], rolled=[], handled=[])
    monkeypatch.setattr(worker, "_session", lambda tenant, user: e.db)
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: e.lease)
    monkeypatch.setattr(worker, "release_job_lease",
                        lambda key, lease, **kw: e.released.append((key, lease)))
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))

    def handle(actor, exc, **ctx):
        e.handled.append((actor, exc, ctx))
        return {"status": "error", "actor": actor, "error": {"type": type(exc).__name__}}

    monkeypatch.setattr(worker, "_handle_actor_error", handle)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    return e


def test_actor_ok_libera_lease_y_cierra(env, monkeypatch):
    monkeypatch.setattr(wd, "emit_source_freshness_alerts", lambda db: {"stale": 1})
    out = worker.dispatch_source_freshness_watchdog.fn(tenant_id=1, user_id="u")
    assert out == {"status": "ok", "actor": "dispatch_source_freshness_watchdog", "stale": 1}
    assert env.released == [("dispatch_source_freshness_watchdog:1", "LEASE")]
    env.db.close.assert_called_once_with()


def test_actor_lease_held_no_trabaja(env, monkeypatch):
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: None)
    called = []
    monkeypatch.setattr(wd, "emit_source_freshness_alerts", lambda db: called.append(db))
    out = worker.dispatch_source_freshness_watchdog.fn(tenant_id=1, user_id="u")
    assert out["reason"] == "lease_held" and called == []
    env.db.close.assert_called_once_with()


def test_actor_error_rollback_lease_y_cierre(env, monkeypatch):
    boom = KeyError("inventory")

    def fail(db):
        raise boom

    monkeypatch.setattr(wd, "emit_source_freshness_alerts", fail)
    out = worker.dispatch_source_freshness_watchdog.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error"
    assert env.handled and env.handled[0][1] is boom
    assert env.rolled == [env.db]
    assert env.released == [("dispatch_source_freshness_watchdog:1", "LEASE")]
    env.db.close.assert_called_once_with()


def test_actor_en_taxonomia_mantenimiento():
    from app.workers.queue_taxonomy import ACTOR_CLASS, MANTENIMIENTO

    assert ACTOR_CLASS["dispatch_source_freshness_watchdog"] == MANTENIMIENTO


# --- PG real: rollback intermedio (pedido por el auditor) --------------------
# Se salta sin GERARAI_TEST_PG_URL; con PG comprueba que el timeout sobrevive
# a CADA rollback interno (capas, conectores, ProPick): SET LOCAL muere con
# la transaccion.

PG_URL = os.environ.get("GERARAI_TEST_PG_URL")


def _pg_session(url):
    """Sesion PG con esquema completo y tenant, idempotente (merge)."""
    import sqlalchemy as sa
    from sqlalchemy.orm import Session as PgSession

    from app.models.entities import Base

    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    Base.metadata.create_all(engine)
    session = PgSession(engine)
    session.merge(Tenant(id=1, external_id="owner"))  # idempotente al repetir
    session.commit()
    session.info["tenant_id"] = 1
    return engine, session


@pytest.mark.skipif(not PG_URL, reason="sin GERARAI_TEST_PG_URL (PG real)")
def test_pg_rollback_intermedio_no_deja_capas_sin_timeout():
    """Con una capa rota en medio, el timeout sigue activo despues (v3/v4).

    En PG real: set_config(is_local=true) + error + rollback deja SHOW
    statement_timeout = 0 (medido). inventory() reaplica el limite tras cada
    rollback, asi que al volver la sesion sigue acotada. Las demas capas
    deben medir ok: solo Documentos falta.
    """
    import sqlalchemy as sa

    from app.services.data_health_service import inventory

    engine, pg_db = _pg_session(PG_URL)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE documents CASCADE"))
    snap = inventory(pg_db, statement_timeout_ms=15000)
    capas = {r["layer"]: r["status"] for r in snap["sources"]}
    assert capas["Documentos"] == "error"
    # Solo Documentos falta: el resto de capas deben medir, no arrastrar error.
    assert capas["Fundamentales"] != "error"
    assert capas["Precios diarios"] != "error"
    assert capas["Noticias"] != "error"
    # Tras el rollback de la capa rota, el limite sigue puesto (v2 lo
    # perdia: SHOW devolvia 0).
    assert pg_db.execute(sa.text("SHOW statement_timeout")).scalar() == "15s"


@pytest.mark.skipif(not PG_URL, reason="sin GERARAI_TEST_PG_URL (PG real)")
def test_pg_rollback_en_conectores_y_propick_conserva_timeout():
    """Rollback en los dos ultimos bloques: el limite se reaplica (v4).

    Sin las tablas connector_states ni propick, ambos bloques hacen
    rollback; al terminar, la sesion debe seguir acotada.
    """
    import sqlalchemy as sa

    from app.services.data_health_service import inventory

    engine, pg_db = _pg_session(PG_URL)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE connector_states CASCADE"))
        conn.execute(sa.text("DROP TABLE IF EXISTS propick_candidates CASCADE"))
        conn.execute(sa.text("DROP TABLE IF EXISTS propick_runs CASCADE"))
    snap = inventory(pg_db, statement_timeout_ms=15000)
    capas = {r["layer"]: r["status"] for r in snap["sources"]}
    assert capas["Conectores"] == "error"
    assert any(c["source"].startswith("ProPicks") and c["status"] == "error"
               for c in snap["connectors"])
    # Las 4 capas de fuentes midieron bien pese a los rollbacks posteriores.
    for capa in ("Fundamentales", "Documentos", "Precios diarios", "Noticias"):
        assert capas[capa] != "error"
    assert pg_db.execute(sa.text("SHOW statement_timeout")).scalar() == "15s"
