"""Migracion 0092 (schedule_13dg_filings): creacion, adopcion idempotente,
cobertura de constraints (PK/FK/unique/indices), rollback y rechazo de
esquemas ajenos."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def _load():
    path = Path(__file__).parents[1] / "alembic/versions/0092_schedule_13dg_filings.py"
    spec = importlib.util.spec_from_file_location("schedule13dg_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model_columns():
    from app.models.entities import Schedule13DGFiling

    return Schedule13DGFiling.__table__.columns


def _create_table(conn, *, with_constraints: bool, with_pk: bool = True):
    """Tabla con las columnas exactas del modelo pero SIN unique/FK/indices
    (el caso del auditor: un create_all o DDL parcial no lanza al adoptar)."""
    metadata = sa.MetaData()
    cols = []
    for column in _model_columns():
        kwargs = {"nullable": column.nullable}
        if column.name == "id":
            kwargs["primary_key"] = with_pk
        cols.append(sa.Column(column.name, column.type, **kwargs))
    sa.Table("schedule_13dg_filings", metadata, *cols)
    metadata.create_all(conn)


def test_upgrade_adoption_and_rollback(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        columns = {c["name"]: c for c in inspect(conn).get_columns("schedule_13dg_filings")}
        assert columns["accession_number"]["nullable"] is False
        assert columns["aggregate_shares"]["nullable"] is True
        assert columns["percent_of_class"]["nullable"] is True
        assert columns["snapshot_date"]["nullable"] is True
        assert any(
            c["column_names"] == ["tenant_id", "accession_number"]
            for c in inspect(conn).get_unique_constraints("schedule_13dg_filings")
        )
        # Idempotente: re-correr upgrade adopta el esquema identico.
        module.upgrade()
        module.downgrade()
        assert not inspect(conn).has_table("schedule_13dg_filings")


def test_upgrade_rejects_foreign_schema(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        conn.exec_driver_sql("CREATE TABLE schedule_13dg_filings (id INTEGER PRIMARY KEY)")
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()


def test_upgrade_adoption_creates_missing_constraints(monkeypatch):
    """Tabla con columnas correctas pero SIN UNIQUE(tenant,accession), SIN FK
    tenant y SIN indices: la adopcion crea lo que falta de forma segura y
    conserva los datos."""
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        _create_table(conn, with_constraints=False)
        conn.exec_driver_sql(
            "INSERT INTO schedule_13dg_filings (tenant_id, accession_number, form, "
            "issuer_cik, is_amendment, holders, parser_version, status, created_at, updated_at) "
            "VALUES (NULL, '0002012383-26-003748', 'SCHEDULE 13G', '1780312', 0, '[]', "
            "'1.0', 'parsed', '2026-10-27 00:00:00', '2026-10-27 00:00:00')"
        )
        module.upgrade()
        inspector = inspect(conn)
        assert any(
            set(c["column_names"]) == {"tenant_id", "accession_number"}
            for c in inspector.get_unique_constraints("schedule_13dg_filings")
        )
        assert any(
            fk["referred_table"] == "tenants"
            and fk["referred_columns"] == ["id"]
            and "tenant_id" in fk["constrained_columns"]
            for fk in inspector.get_foreign_keys("schedule_13dg_filings")
        )
        indexes = {i["name"] for i in inspector.get_indexes("schedule_13dg_filings")}
        assert "ix_schedule13dg_issuer" in indexes
        assert "ix_schedule13dg_ticker" in indexes
        # Datos preservados.
        rows = conn.exec_driver_sql(
            "SELECT accession_number FROM schedule_13dg_filings"
        ).all()
        assert rows == [("0002012383-26-003748",)]
        # La unique creada de verdad: un duplicado falla. Con tenant NO NULL:
        # en SQLite/Postgres los NULL se consideran distintos y una UNIQUE no
        # deduplicaria (NULL, accession) — limitacion heredada del esquema,
        # la dedup del tenant NULL la hace la SELECT previa de persist_filing.
        from sqlalchemy.exc import IntegrityError

        conn.exec_driver_sql(
            "INSERT INTO schedule_13dg_filings (tenant_id, accession_number, form, "
            "issuer_cik, is_amendment, holders, parser_version, status, created_at, updated_at) "
            "VALUES (7, '0002012383-26-009999', 'SCHEDULE 13G', '1780312', 0, '[]', "
            "'1.0', 'parsed', '2026-10-27 00:00:00', '2026-10-27 00:00:00')"
        )
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "INSERT INTO schedule_13dg_filings (tenant_id, accession_number, form, "
                "issuer_cik, is_amendment, holders, parser_version, status, created_at, updated_at) "
                "VALUES (7, '0002012383-26-009999', 'SCHEDULE 13G', '1780312', 0, '[]', "
                "'1.0', 'parsed', '2026-10-27 00:00:00', '2026-10-27 00:00:00')"
            )


def test_upgrade_adoption_rejects_missing_primary_key(monkeypatch):
    """Columnas correctas pero sin PK en id: esquema ajeno, no se adopta."""
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        _create_table(conn, with_constraints=False, with_pk=False)
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()
