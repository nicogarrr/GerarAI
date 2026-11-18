"""Migracion 0137 (form144_notices): creacion, adopcion idempotente,
cobertura de constraints (PK/FK/unique/indices), rollback y rechazo de
esquemas ajenos. Espejo de test_0092_schedule13dg_migration."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def _load():
    path = Path(__file__).parents[1] / "alembic/versions/0137_form144_notices.py"
    spec = importlib.util.spec_from_file_location("form144_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model_columns():
    from app.models.entities import Form144Notice

    return Form144Notice.__table__.columns


def _create_table(conn, *, with_pk: bool = True):
    """Tabla con las columnas exactas del modelo pero SIN unique/FK/indices
    (el caso del auditor: un create_all o DDL parcial no lanza al adoptar)."""
    metadata = sa.MetaData()
    cols = []
    for column in _model_columns():
        kwargs = {"nullable": column.nullable}
        if column.name == "id":
            kwargs["primary_key"] = with_pk
        cols.append(sa.Column(column.name, column.type, **kwargs))
    sa.Table("form144_notices", metadata, *cols)
    metadata.create_all(conn)


def test_upgrade_adoption_and_rollback(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        columns = {c["name"]: c for c in inspect(conn).get_columns("form144_notices")}
        assert columns["accession_number"]["nullable"] is False
        assert columns["shares_to_sell"]["nullable"] is True
        assert columns["aggregate_market_value"]["nullable"] is True
        assert columns["approx_sale_date"]["nullable"] is True
        assert columns["remarks"]["nullable"] is True
        assert any(
            c["column_names"] == ["tenant_id", "accession_number"]
            for c in inspect(conn).get_unique_constraints("form144_notices")
        )
        # Idempotente: re-correr upgrade adopta el esquema identico.
        module.upgrade()
        module.downgrade()
        assert not inspect(conn).has_table("form144_notices")


def test_upgrade_adopts_table_without_constraints(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        _create_table(conn)
        module.upgrade()
        assert any(
            c["column_names"] == ["tenant_id", "accession_number"]
            for c in inspect(conn).get_unique_constraints("form144_notices")
        )
        index_columns = {
            tuple(i["column_names"]) for i in inspect(conn).get_indexes("form144_notices")
        }
        assert ("issuer_cik",) in index_columns
        assert ("tenant_id", "issuer_ticker", "filing_date") in index_columns


def test_upgrade_rejects_foreign_schema(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        conn.exec_driver_sql("CREATE TABLE form144_notices (id INTEGER PRIMARY KEY)")
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()
