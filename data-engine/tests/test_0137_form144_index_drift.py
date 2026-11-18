"""0137 y el indice por tenant: el modelo hereda tenant_id con index=True
(ix_form144_notices_tenant_id) y la migracion debe crearlo, tanto al crear la
tabla como al adoptar una pre-existente (guard de deriva modelo/migracion de
CI, PG17). Se comprueba por NOMBRE, no solo por columnas."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

DATA_ENGINE = Path(__file__).parents[1]
INDEX = "ix_form144_notices_tenant_id"
EXPECTED = {
    INDEX: ["tenant_id"],
    "ix_form144_issuer": ["issuer_cik"],
    "ix_form144_tenant_ticker_date": ["tenant_id", "issuer_ticker", "filing_date"],
}


def _load():
    path = DATA_ENGINE / "alembic/versions/0137_form144_notices.py"
    spec = importlib.util.spec_from_file_location("form144_migration_idx", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _names(conn) -> dict[str, list[str]]:
    return {i["name"]: i["column_names"] for i in inspect(conn).get_indexes("form144_notices")}


def _bare_table(conn):
    """Tabla del modelo sin constraints ni indices (create_all parcial)."""
    from app.models.entities import Form144Notice

    metadata = sa.MetaData()
    cols = [
        sa.Column(c.name, c.type, nullable=c.nullable, primary_key=(c.name == "id"))
        for c in Form144Notice.__table__.columns
    ]
    sa.Table("form144_notices", metadata, *cols)
    metadata.create_all(conn)


def test_modelo_declara_el_indice_por_tenant():
    from app.models.entities import Form144Notice

    declared = {i.name: [c.name for c in i.columns] for i in Form144Notice.__table__.indexes}
    assert declared == EXPECTED


def test_creacion_crea_el_indice_por_tenant(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        assert _names(conn) == EXPECTED


def test_adopcion_anade_el_indice_por_tenant_y_es_idempotente(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        _bare_table(conn)
        assert _names(conn) == {}
        module.upgrade()
        assert _names(conn) == EXPECTED
        module.upgrade()  # segunda corrida: no duplica ni falla
        assert _names(conn) == EXPECTED


def test_adopcion_con_el_indice_ya_presente_no_lo_recrea(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        conn.execute(sa.text("DELETE FROM migration_table_provenance"))
        module.upgrade()  # adopta una tabla que ya tiene todo
        assert _names(conn) == EXPECTED


def test_downgrade_coherente_borra_lo_creado_y_conserva_lo_adoptado(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        module.downgrade()
        assert not inspect(conn).has_table("form144_notices")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        _bare_table(conn)
        module.upgrade()
        module.downgrade()
        assert inspect(conn).has_table("form144_notices")
        assert INDEX in _names(conn)


def test_cadena_a_head_no_deja_deriva_en_form144_notices(tmp_path):
    """Autogenerate (compare_metadata) sobre la cadena completa migrada a head:
    cero diferencias para form144_notices (falla sin el indice por tenant)."""
    from app.core.database import Base

    url = f"sqlite:///{(tmp_path / 'chain.db').as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=DATA_ENGINE, env={**os.environ, "DATABASE_URL": url},
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn,
                opts={
                    "target_metadata": Base.metadata,
                    "include_object": lambda obj, name, type_, reflected, compare_to: (
                        name == "form144_notices"
                        if type_ == "table"
                        else getattr(getattr(obj, "table", None), "name", None) == "form144_notices"
                    ),
                },
            )
            diffs = compare_metadata(ctx, Base.metadata)
    finally:
        engine.dispose()
    assert diffs == [], diffs


def test_deriva_en_postgres_real_sin_diferencias_de_form144():
    """Mismo guard que el job 'Postgres migration round trip': BD scratch
    migrada a head y compare_metadata completo; ninguna linea de deriva
    nombra form144_notices. Solo corre con el Postgres de CI."""
    from tests import test_alembic_chain as chain

    url = chain._url_postgres_ci()
    if not url:
        pytest.skip("Runs only on the CI Postgres migration service")
    lines = chain._deriva_actual(url)
    assert [line for line in lines if "form144_notices" in line] == []


# --- ramas de adopcion y downgrade de la migracion --------------------------


def _table(conn, *, extra=(), pk=True, nullable_accession=False, fk=None, unique=False,
           drop_col=None, shrink=False):
    """Tabla del modelo con variantes para probar cada rama de adopcion."""
    from app.models.entities import Form144Notice

    metadata = sa.MetaData()
    sa.Table("tenants", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("otra", metadata, sa.Column("id", sa.Integer, primary_key=True))
    cols = []
    for c in Form144Notice.__table__.columns:
        if c.name == drop_col:
            continue
        kwargs = {"nullable": c.nullable, "primary_key": pk and c.name == "id"}
        if c.name == "accession_number" and nullable_accession:
            kwargs["nullable"] = True
        args = [c.name, sa.String(5) if (shrink and c.name == "issuer_cik") else c.type]
        if c.name == "tenant_id" and fk:
            args.append(sa.ForeignKey(fk))
        cols.append(sa.Column(*args, **kwargs))
    cols.extend(extra)
    items = list(cols)
    if unique:
        items.append(sa.UniqueConstraint("tenant_id", "accession_number"))
    sa.Table("form144_notices", metadata, *items)
    metadata.create_all(conn)


def _adopt(monkeypatch, **kw):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    conn = engine.connect()
    trans = conn.begin()
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
    _table(conn, **kw)
    return module, conn, trans


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"extra": [sa.Column("rara", sa.Integer)]}, "schema mismatch"),
        ({"drop_col": "remarks"}, "schema mismatch"),
        ({"nullable_accession": True}, "schema mismatch"),
        ({"shrink": True}, "schema mismatch"),
        ({"pk": False}, "sin PK"),
        ({"fk": "otra.id"}, "FK tenant ajena"),
    ],
)
def test_adopcion_rechaza_esquemas_ajenos(monkeypatch, kw, message):
    module, conn, trans = _adopt(monkeypatch, **kw)
    try:
        with pytest.raises(RuntimeError, match=message):
            module.upgrade()
    finally:
        trans.rollback()
        conn.close()


def test_adopcion_con_unique_sin_fk_solo_anade_la_fk(monkeypatch):
    module, conn, trans = _adopt(monkeypatch, unique=True)
    try:
        module.upgrade()
        insp = inspect(conn)
        assert insp.get_foreign_keys("form144_notices")
        assert _names(conn) == EXPECTED
    finally:
        trans.rollback()
        conn.close()


def test_adopcion_con_fk_sin_unique_solo_anade_la_unique(monkeypatch):
    module, conn, trans = _adopt(monkeypatch, fk="tenants.id")
    try:
        module.upgrade()
        assert any(
            set(u["column_names"]) == {"tenant_id", "accession_number"}
            for u in inspect(conn).get_unique_constraints("form144_notices")
        )
        assert _names(conn) == EXPECTED
    finally:
        trans.rollback()
        conn.close()


def test_downgrade_sin_tabla_de_procedencia_conserva_la_tabla(monkeypatch):
    module, conn, trans = _adopt(monkeypatch)
    try:
        module.downgrade()  # sin marca: no toca nada y no falla sin la tabla auxiliar
        assert inspect(conn).has_table("form144_notices")
        assert not inspect(conn).has_table("migration_table_provenance")
    finally:
        trans.rollback()
        conn.close()


def test_downgrade_creada_pero_tabla_ya_borrada_solo_limpia_la_marca(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        conn.execute(sa.text("DROP TABLE form144_notices"))
        module.downgrade()
        left = conn.execute(sa.text("SELECT count(*) FROM migration_table_provenance")).scalar()
        assert left == 0
