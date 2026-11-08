"""Ruta /admin/db-metrics: ramas por dialecto, errores y gate de operaciones.

Sobre main solo se ejercitaba el camino feliz sqlite del agregado. Aqui se
cubren las ramas PostgreSQL y dialecto desconocido, los fallos de pool y de
consulta (que deben degradar a dicts de error, no tumbar la ruta) y el gate
de ``cache_global_invalidation_allowed``.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import db_metrics as mod
from app.models.entities import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        yield db
    engine.dispose()


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._rows[0] if self._rows else None


def _fake_pg_db(responses):
    """db de mentira con dialecto postgres y respuestas encoladas por llamada."""
    calls = []

    def execute(clause):
        calls.append(str(clause))
        return responses.pop(0)

    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    return SimpleNamespace(bind=bind, execute=execute)


def test_pool_stats_degrada_a_error_cuando_el_pool_falla(monkeypatch):
    class BrokenPool:
        def size(self):
            raise RuntimeError("pool roto")

    monkeypatch.setattr(mod, "engine", SimpleNamespace(pool=BrokenPool()))
    assert mod._get_pool_stats() == {"error": "RuntimeError"}


def test_disk_usage_sqlite_devuelve_paginas(db):
    out = mod._get_disk_usage(db)
    assert out["dialect"] == "sqlite"
    assert out["page_count"] > 0
    assert out["page_size"] > 0
    assert out["database_size_bytes"] == out["page_count"] * out["page_size"]


def test_disk_usage_postgres_devuelve_tablas():
    db = _fake_pg_db([
        _FakeResult([(10 * 1024 * 1024,)]),
        _FakeResult([("public.companies", 2097152, 1048576, 1048576)]),
    ])
    out = mod._get_disk_usage(db)
    assert out["dialect"] == "postgresql"
    assert out["database_size_mb"] == 10.0
    assert out["top_tables"][0]["table"] == "public.companies"
    assert out["top_tables"][0]["total_bytes"] == 2097152


def test_disk_usage_dialecto_desconocido():
    db = _fake_pg_db([])
    db.bind.dialect.name = "oracle"
    out = mod._get_disk_usage(db)
    assert out["dialect"] == "oracle"
    assert "Unsupported dialect" in out["error"]


def test_disk_usage_error_de_consulta_degrada_a_dict():
    def execute(clause):
        raise RuntimeError("sin permisos")

    bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    db = SimpleNamespace(bind=bind, execute=execute)
    out = mod._get_disk_usage(db)
    assert out["error"] == "RuntimeError"
    assert "sin permisos" in out["message"]


def test_table_bloat_solo_postgres(db):
    out = mod._get_table_bloat(db)
    assert out["dialect"] == "sqlite"
    assert "only available for PostgreSQL" in out["note"]


def test_table_bloat_postgres_lista_tablas():
    db = _fake_pg_db([
        _FakeResult([("public.prices", 2097152, 5000, 10000, 33.33)]),
    ])
    out = mod._get_table_bloat(db)
    assert out["dialect"] == "postgresql"
    row = out["bloated_tables"][0]
    assert row["table"] == "public.prices"
    assert row["dead_tuples"] == 5000
    assert row["dead_tuple_percent"] == 33.33


def test_table_bloat_error_degrada_a_dict():
    def execute(clause):
        raise RuntimeError("stats no disponibles")

    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    db = SimpleNamespace(bind=bind, execute=execute)
    out = mod._get_table_bloat(db)
    assert out["error"] == "RuntimeError"


def test_collect_metrics_mapea_excepciones_a_errores(db, monkeypatch):
    def boom_pool():
        raise RuntimeError("pool")

    def boom_disk(db_):
        raise RuntimeError("disk")

    def boom_bloat(db_):
        raise RuntimeError("bloat")

    monkeypatch.setattr(mod, "_get_pool_stats", boom_pool)
    monkeypatch.setattr(mod, "_get_disk_usage", boom_disk)
    monkeypatch.setattr(mod, "_get_table_bloat", boom_bloat)
    out = asyncio.run(mod._collect_metrics(db))
    assert out == {
        "pool": {"error": "RuntimeError"},
        "disk_usage": {"error": "RuntimeError"},
        "table_bloat": {"error": "RuntimeError"},
    }


def test_ruta_404_con_gate_de_operaciones_cerrado(db, monkeypatch):
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: SimpleNamespace(cache_global_invalidation_allowed=False),
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.db_metrics(db=db))
    assert exc.value.status_code == 404


def test_ruta_devuelve_metricas_con_gate_abierto(db, monkeypatch):
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: SimpleNamespace(cache_global_invalidation_allowed=True),
    )
    esperado = {"pool": {}, "disk_usage": {}, "table_bloat": {}}

    async def fake_collect(db_):
        assert db_ is db
        return esperado

    # _collect_metrics reparte el trabajo con asyncio.to_thread: con SQLite
    # en memoria eso cruza hilos, asi que la agregacion real se ejercita en
    # los tests de _collect_metrics y aqui solo se fija la delegacion.
    monkeypatch.setattr(mod, "_collect_metrics", fake_collect)
    assert asyncio.run(mod.db_metrics(db=db)) is esperado
