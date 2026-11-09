"""init_db forward-compat de app/core/database.py con esquemas viejos reales.

El engine global se revia (monkeypatch) a un SQLite en memoria donde las
tablas "viejas" se crean con SQL manual ANTES de init_db; create_all es
idempotente y no las toca, asi que los ALTERs y el rebuild trabajan sobre
el esquema viejo de verdad. No hay dobles del mecanismo de migracion.

Cubre: rebuild de thesis_versions (NOT NULL -> nullable, datos e indices
preservados), ALTERs de investment_principles / thesis_versions /
news_events / positions / tenant_id en tablas tenant-owned, registro de
fallos sin lanzar (rebuild roto y _execute_optional), y _quote_identifiers.

NO se prueba: Postgres real (el rebuild y los ALTERs son el camino sqlite),
ni la semantica de los valores migrados (no hay logica de valoracion aqui,
solo forma del esquema).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

import app.core.database as coredb


@pytest.fixture
def engine_viejo(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(coredb, "engine", engine)
    # estado global del modulo: lista fresca por test (aislamiento, como _CACHE)
    monkeypatch.setattr(coredb, "_SCHEMA_MIGRATION_ERRORS", [])
    try:
        yield engine
    finally:
        engine.dispose()


def _columnas(engine, tabla):
    return {
        c["name"]: c for c in inspect(engine).get_columns(tabla)
    }


def _crea_thesis_vieja(engine, *, not_null=True, con_fingerprint=True):
    nul = " NOT NULL" if not_null else ""
    extra = ", input_fingerprint VARCHAR(64)" if con_fingerprint else ""
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE thesis_versions ("
                "id INTEGER PRIMARY KEY, thesis_id INTEGER,"
                f"current_price NUMERIC(24,6){nul}, bear_value NUMERIC(24,6){nul},"
                f"base_value NUMERIC(24,6){nul}, bull_value NUMERIC(24,6){nul},"
                f"expected_value NUMERIC(24,6){nul}, margin_of_safety NUMERIC(24,6){nul},"
                f"payload TEXT{extra})"
            )
        )
        conn.execute(
            text(
                "INSERT INTO thesis_versions (id, thesis_id, current_price,"
                " bear_value, base_value, bull_value, expected_value,"
                " margin_of_safety, payload) VALUES"
                " (1, 7, 10.5, 8.0, 10.0, 12.0, 10.0, 0.05, 'datos')"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX ix_thesis_versions_thesis "
                "ON thesis_versions (thesis_id)"
            )
        )
        conn.commit()


def test_rebuild_quita_not_null_y_preserva_datos_e_indices(engine_viejo):
    _crea_thesis_vieja(engine_viejo, not_null=True)
    coredb.init_db()
    cols = _columnas(engine_viejo, "thesis_versions")
    for columna in (
        "current_price",
        "bear_value",
        "base_value",
        "bull_value",
        "expected_value",
        "margin_of_safety",
    ):
        assert cols[columna]["nullable"] is True, columna
    with engine_viejo.connect() as conn:
        fila = conn.execute(
            text("SELECT thesis_id, current_price, payload FROM thesis_versions")
        ).one()
        assert (fila.thesis_id, fila.current_price, fila.payload) == (7, 10.5, "datos")
        indices = {
            r[1]
            for r in conn.execute(text("PRAGMA index_list(thesis_versions)")).all()
        }
        assert "ix_thesis_versions_thesis" in indices
    assert coredb._SCHEMA_MIGRATION_ERRORS == []


def test_rebuild_roto_se_registra_sin_lanzar(engine_viejo):
    _crea_thesis_vieja(engine_viejo, not_null=True)
    with engine_viejo.connect() as conn:  # nombre colisionado: el CREATE falla
        conn.execute(text("CREATE TABLE thesis_versions__nullable (id INTEGER)"))
        conn.commit()
    coredb.init_db()
    errores = [
        e
        for e in coredb._SCHEMA_MIGRATION_ERRORS
        if e["statement"].startswith("REBUILD thesis_versions")
    ]
    assert len(errores) == 1
    # y la tabla original sigue intacta (no hubo DROP)
    assert _columnas(engine_viejo, "thesis_versions")["current_price"]["nullable"] is False


def test_alters_forward_compat_en_tablas_viejas(engine_viejo):
    with engine_viejo.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE investment_principles ("
                "id INTEGER PRIMARY KEY, tenant_id INTEGER, text TEXT)"
            )
        )
        conn.execute(text("INSERT INTO investment_principles VALUES (1, 1, 'p')"))
        conn.execute(
            text("CREATE TABLE news_events (id INTEGER PRIMARY KEY, title TEXT)")
        )
        conn.execute(
            text(
                "CREATE TABLE positions (id INTEGER PRIMARY KEY, portfolio_id INTEGER)"
            )
        )
        conn.execute(
            text("CREATE TABLE fundamental_drivers (id INTEGER PRIMARY KEY)")
        )
        conn.execute(
            text(
                "CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT,"
                " source_type TEXT, metadata TEXT)"
            )
        )
        conn.commit()
    _crea_thesis_vieja(engine_viejo, not_null=False, con_fingerprint=False)
    coredb.init_db()
    principios = _columnas(engine_viejo, "investment_principles")
    for columna in (
        "principle_fingerprint",
        "semantic_duplicate_of_id",
        "canonical_principle_id",
        "version",
        "superseded_by_id",
    ):
        assert columna in principios, columna
    with engine_viejo.connect() as conn:
        huella = conn.execute(
            text("SELECT principle_fingerprint FROM investment_principles WHERE id = 1")
        ).scalar()
        assert huella and len(huella) == 64  # backfill del UPDATE
    assert "metadata" in _columnas(engine_viejo, "news_events")
    posiciones = _columnas(engine_viejo, "positions")
    for columna in ("base_currency", "fx_rate", "unrealized_pnl_base"):
        assert columna in posiciones, columna
    drivers = _columnas(engine_viejo, "fundamental_drivers")
    for columna in ("segment", "source", "time_basis"):
        assert columna in drivers, columna
    assert "tenant_id" in _columnas(engine_viejo, "documents")
    assert "input_fingerprint" in _columnas(engine_viejo, "thesis_versions")
    assert coredb._SCHEMA_MIGRATION_ERRORS == []


def test_execute_optional_registra_y_sigue(engine_viejo):
    assert coredb._execute_optional("ALTER imposible", "ALTER TABLE no_existe ADD COLUMN x") is False
    assert coredb._SCHEMA_MIGRATION_ERRORS == [
        {"statement": "ALTER imposible", "error": "OperationalError"}
    ]
    assert (
        coredb._execute_optional(
            "CREATE ok", "CREATE TABLE t_ok (id INTEGER PRIMARY KEY)"
        )
        is True
    )
    # el fallo anterior no bloquea los siguientes
    assert "t_ok" in inspect(engine_viejo).get_table_names()


def test_quote_identifiers_escapa_comillas():
    assert coredb._quote_identifiers(['na"me', "plain"]) == ['"na""me"', '"plain"']
