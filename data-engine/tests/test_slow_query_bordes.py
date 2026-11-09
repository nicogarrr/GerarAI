"""Bordes de ``app.core.slow_query``: idempotencia, cola vacia y log de lentas.

Lo que cada test demuestra:
- ``install`` es idempotente (linea 34): la segunda llamada no registra
  listeners nuevos (conteo exacto de listeners before/after antes y despues).
- ``_after_cursor_execute`` sin tiempos pendientes sale sin tocar ``conn.info``
  (linea 59).
- Una consulta lenta se registra con elapsed exacto y la consulta saneada
  (68-72), truncada a 503 chars cuando supera 500 (rama 69-70) y sin
  truncar cuando no (rama 69->72).
- Una consulta por debajo del umbral no registra nada (rama 64->57).

La fixture registra listeners sentinel antes de cada test y, en el finally,
retira con ``event.remove`` los listeners que el test haya anadido, deja los
sentinel intactos y hace ``dispose`` del engine: ningun listener queda
registrado al salir. ``_INSTALLED`` se dobla con monkeypatch (restaura solo)
y el reloj se fija con una constante para asserts de mensaje exactos. Engines
SQLite en memoria locales a cada test; sin red.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text

from app.core import slow_query


def _listeners(engine, name):
    return list(getattr(engine.dispatch, name).listeners)


@pytest.fixture
def engine_controlado(monkeypatch):
    """Engine SQLite con listeners sentinel y limpieza exacta al salir.

    Espia ``event.listens_for`` para capturar las funciones originales que
    el test registre (``dispatch.listeners`` devuelve wrappers internos que
    ``event.remove`` no acepta) y las retira en el finally; los sentinel,
    registrados antes del espia, quedan intactos.
    """
    engine = create_engine("sqlite:///:memory:")

    def sentinel_before(*args):
        pass

    def sentinel_after(*args):
        pass

    event.listens_for(engine, "before_cursor_execute")(sentinel_before)
    event.listens_for(engine, "after_cursor_execute")(sentinel_after)
    snap = {name: _listeners(engine, name) for name in ("before_cursor_execute", "after_cursor_execute")}
    registrados = []
    real_listens_for = event.listens_for

    def espia(target, identifier, *args, **kwargs):
        decorador = real_listens_for(target, identifier, *args, **kwargs)

        def envoltura(fn):
            registrados.append((target, identifier, fn))
            return decorador(fn)

        return envoltura

    monkeypatch.setattr(event, "listens_for", espia)
    try:
        yield engine, snap
    finally:
        for target, identifier, fn in registrados:
            event.remove(target, identifier, fn)
        # Solo quedan los sentinel, en su orden original.
        assert _listeners(engine, "before_cursor_execute") == snap["before_cursor_execute"]
        assert _listeners(engine, "after_cursor_execute") == snap["after_cursor_execute"]
        engine.dispose()


def test_install_es_idempotente(monkeypatch, engine_controlado):
    engine, snap = engine_controlado
    monkeypatch.setattr(slow_query, "_INSTALLED", False)
    slow_query.install(engine)
    assert len(_listeners(engine, "before_cursor_execute")) == len(snap["before_cursor_execute"]) + 1
    assert len(_listeners(engine, "after_cursor_execute")) == len(snap["after_cursor_execute"]) + 1
    slow_query.install(engine)  # segunda llamada: sale por la linea 34
    # Sin listeners nuevos: el mutante sin guarda registraria un segundo par.
    assert len(_listeners(engine, "before_cursor_execute")) == len(snap["before_cursor_execute"]) + 1
    assert len(_listeners(engine, "after_cursor_execute")) == len(snap["after_cursor_execute"]) + 1
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        # Un solo before + un solo after: la pila queda vacia.
        assert conn.info["query_start_time"] == []


def test_after_sin_tiempos_pendientes_no_toca_conn_info(monkeypatch, engine_controlado):
    engine, _ = engine_controlado
    monkeypatch.setattr(slow_query, "_INSTALLED", False)
    slow_query.install(engine)
    conn = SimpleNamespace(info={})
    engine.dispatch.after_cursor_execute(conn, None, "SELECT 1", (), None, False)
    assert conn.info == {}


def test_consulta_lenta_se_registra_con_truncado(monkeypatch, caplog, engine_controlado):
    engine, _ = engine_controlado
    monkeypatch.setattr(slow_query, "_INSTALLED", False)
    monkeypatch.setattr(slow_query.time, "monotonic", lambda: 100.25)
    slow_query.install(engine, threshold_s=0.1)
    statement = "S" * 600 + "\n"
    conn = SimpleNamespace(info={"query_start_time": [100.0]})
    with caplog.at_level(logging.WARNING, logger="app.core.slow_query"):
        engine.dispatch.after_cursor_execute(conn, None, statement, (), None, False)
    assert [r.getMessage() for r in caplog.records] == ["slow_query: 0.250s | " + "S" * 500 + "..."]


def test_consulta_lenta_corta_no_se_trunca(monkeypatch, caplog, engine_controlado):
    engine, _ = engine_controlado
    monkeypatch.setattr(slow_query, "_INSTALLED", False)
    monkeypatch.setattr(slow_query.time, "monotonic", lambda: 100.25)
    slow_query.install(engine, threshold_s=0.1)
    conn = SimpleNamespace(info={"query_start_time": [100.0]})
    with caplog.at_level(logging.WARNING, logger="app.core.slow_query"):
        engine.dispatch.after_cursor_execute(conn, None, "SELECT 1\nFROM t", (), None, False)
    assert [r.getMessage() for r in caplog.records] == ["slow_query: 0.250s | SELECT 1 FROM t"]


def test_consulta_rapida_no_registra(monkeypatch, caplog, engine_controlado):
    engine, _ = engine_controlado
    monkeypatch.setattr(slow_query, "_INSTALLED", False)
    monkeypatch.setattr(slow_query.time, "monotonic", lambda: 100.001)
    slow_query.install(engine, threshold_s=10.0)
    conn = SimpleNamespace(info={"query_start_time": [100.0]})
    with caplog.at_level(logging.WARNING, logger="app.core.slow_query"):
        engine.dispatch.after_cursor_execute(conn, None, "SELECT 1", (), None, False)
    assert caplog.records == []
