from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

from tests.test_0137_form144_migration import _create_table, _load


def _create_table_nullable_flipped(conn):
    metadata = sa.MetaData()
    cols = []
    from app.models.entities import Form144Notice

    for column in Form144Notice.__table__.columns:
        nullable = (not column.nullable) if column.name == "accession_number" else column.nullable
        cols.append(sa.Column(column.name, column.type, nullable=nullable, primary_key=(column.name == "id")))
    sa.Table("form144_notices", metadata, *cols)
    metadata.create_all(conn)


def test_adoption_rejects_nullable_mismatch(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        _create_table_nullable_flipped(conn)
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()


def test_adoption_rejects_string_length_mismatch(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        conn.exec_driver_sql(
            "CREATE TABLE form144_notices (id INTEGER PRIMARY KEY, accession_number VARCHAR(41))"
        )
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()


def test_adoption_rejects_missing_pk(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        _create_table(conn, with_pk=False)
        with pytest.raises(RuntimeError, match="sin PK"):
            module.upgrade()


def test_adoption_with_full_constraints_marks_adopted(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE tenants (id INTEGER PRIMARY KEY)")
        _create_table(conn)
        ops = Operations(MigrationContext.configure(conn))
        with ops.batch_alter_table("form144_notices") as batch:
            batch.create_unique_constraint("uq_existing", ["tenant_id", "accession_number"])
            batch.create_foreign_key("fk_ok", "tenants", ["tenant_id"], ["id"])
        monkeypatch.setattr(module, "op", ops)
        module.upgrade()
        mode = conn.scalar(
            sa.text(
                "SELECT mode FROM migration_table_provenance "
                "WHERE revision='0137_form144_notices' AND table_name='form144_notices'"
            )
        )
        assert mode == "adopted"
        module.downgrade()
        assert sa.inspect(conn).has_table("form144_notices")  # adoptada: no se borra


def test_downgrade_without_provenance_row_keeps_table(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()  # created + marca created
        conn.execute(
            sa.text(
                "DELETE FROM migration_table_provenance "
                "WHERE revision='0137_form144_notices' AND table_name='form144_notices'"
            )
        )
        module.downgrade()  # sin marca: lo seguro es conservar
        assert sa.inspect(conn).has_table("form144_notices")


