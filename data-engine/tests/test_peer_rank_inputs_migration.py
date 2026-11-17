"""Online expansion, row-lock races, resumable batches and bounded DDL locks."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError

from app.valuation.peer_rank_projection import backfill_batch


def _migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0136_peer_rank_inputs.py"
    spec = importlib.util.spec_from_file_location("peer_rank_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bind(monkeypatch, migration, connection):
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        get_bind=lambda: connection, execute=lambda sql: connection.execute(text(sql)),
    ))


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_migration_dialect_and_order(monkeypatch, dialect):
    migration = _migration()
    statements = []
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name=dialect)),
        execute=statements.append,
    ))
    migration.upgrade()
    migration.downgrade()
    if dialect == "sqlite":
        assert statements == []
    else:
        assert len(statements) == 11
        assert "lock_timeout" in statements[0]
        assert "CREATE OR REPLACE FUNCTION" in statements[1]
        assert "ADD COLUMN" in statements[2]
        assert "GENERATED ALWAYS" not in statements[2]
        assert "TRIGGER" in statements[5]
        assert "DROP TRIGGER" in statements[7]
        assert "DROP COLUMN" in statements[8]


@pytest.mark.parametrize("size", [0, -1, 101, True, None, "25", 1.5])
def test_batch_size_guard(size):
    with pytest.raises(ValueError):
        backfill_batch(None, size)


@pytest.fixture
def pg():
    url = os.environ.get("PEER_RATIO_TEST_PG_URL")
    if not url:
        pytest.skip("Set PEER_RATIO_TEST_PG_URL for disposable-schema PG tests")
    engine = create_engine(url)
    schema = "peer_online_" + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    @event.listens_for(engine, "begin")
    def search_path(conn):
        conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE valuation_outputs (id integer primary key, output_payload json)"))
        conn.execute(text("INSERT INTO valuation_outputs SELECT n, json_build_object('expected_value',150,'current_price',100) FROM generate_series(1,5) n"))
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_pg_repeat_resume_rollback_and_no_rewrite(pg, monkeypatch):
    migration = _migration()
    with pg.begin() as conn:
        before = conn.execute(text("SELECT pg_relation_filenode('valuation_outputs')")).scalar()
        _bind(monkeypatch, migration, conn)
        migration.upgrade()
        migration.upgrade()
        assert conn.execute(text("SELECT pg_relation_filenode('valuation_outputs')")).scalar() == before
        assert conn.execute(text("SELECT count(*) FROM valuation_outputs WHERE peer_rank_inputs IS NULL")).scalar() == 5
        assert len(backfill_batch(conn, 2)) == 2
    # Pause/disconnect. Existing rows stay usable via fallback, progress survives.
    with pg.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM valuation_outputs WHERE peer_rank_inputs IS NULL")).scalar() == 3
        assert len(backfill_batch(conn, 2)) == 2
    with pg.connect() as conn:
        tx = conn.begin()
        assert len(backfill_batch(conn, 2)) == 1
        tx.rollback()  # Interrupted batch must not falsely mark a row complete.
    with pg.begin() as conn:
        assert len(backfill_batch(conn, 2)) == 1
        assert backfill_batch(conn, 2) == []
        assert conn.execute(text("SELECT count(*) FROM valuation_outputs WHERE peer_rank_inputs IS NULL")).scalar() == 0
        _bind(monkeypatch, migration, conn)
        migration.downgrade()
        migration.downgrade()
        migration.upgrade()
        assert conn.execute(text("SELECT count(*) FROM valuation_outputs WHERE peer_rank_inputs IS NULL")).scalar() == 5
        assert len(backfill_batch(conn, 100)) == 5
        assert conn.execute(text("SELECT peer_rank_inputs FROM valuation_outputs WHERE id=1")).scalar() == [None, None, None, 150, None, 100]


def test_pg_writer_first_skip_locked_then_resume(pg, monkeypatch):
    migration = _migration()
    with pg.begin() as conn:
        _bind(monkeypatch, migration, conn)
        migration.upgrade()
    with pg.connect() as writer, pg.connect() as batch:
        wt, bt = writer.begin(), batch.begin()
        writer.execute(text("UPDATE valuation_outputs SET output_payload=json_build_object('expected_value',240,'current_price',100) WHERE id=1"))
        touched = backfill_batch(batch, 100)
        assert set(touched) == {2, 3, 4, 5}
        bt.commit()
        wt.commit()
    with pg.begin() as conn:
        assert backfill_batch(conn) == []
        assert conn.execute(text("SELECT peer_rank_inputs FROM valuation_outputs WHERE id=1")).scalar() == [None, None, None, 240, None, 100]


def test_pg_backfill_first_writer_retry_preserves_latest(pg, monkeypatch):
    migration = _migration()
    with pg.begin() as conn:
        _bind(monkeypatch, migration, conn)
        migration.upgrade()
    with pg.connect() as batch, pg.connect() as writer:
        bt, wt = batch.begin(), writer.begin()
        assert backfill_batch(batch, 1) == [1]
        writer.execute(text("SET LOCAL lock_timeout = '50ms'"))
        with pytest.raises(DBAPIError) as error:
            writer.execute(text("UPDATE valuation_outputs SET output_payload=json_build_object('expected_value',310,'current_price',100) WHERE id=1"))
        assert error.value.orig.sqlstate == '55P03'
        wt.rollback()
        bt.commit()
        with writer.begin():
            writer.execute(text("UPDATE valuation_outputs SET output_payload=json_build_object('expected_value',310,'current_price',100) WHERE id=1"))
    with pg.begin() as conn:
        assert conn.execute(text("SELECT peer_rank_inputs FROM valuation_outputs WHERE id=1")).scalar() == [None, None, None, 310, None, 100]
        # Explicit attempts to replace the projection cannot detach it from JSON.
        conn.execute(text("UPDATE valuation_outputs SET peer_rank_inputs='[]'::json WHERE id=1"))
        assert conn.execute(text("SELECT peer_rank_inputs FROM valuation_outputs WHERE id=1")).scalar() == [None, None, None, 310, None, 100]
        conn.execute(text("INSERT INTO valuation_outputs VALUES (6, 'null'::json, NULL)"))
        assert conn.execute(text("SELECT peer_rank_inputs FROM valuation_outputs WHERE id=6")).scalar() == [None] * 6


def test_pg_lock_timeout_is_atomic_and_retryable(pg, monkeypatch):
    migration = _migration()
    with pg.connect() as reader, pg.connect() as ddl:
        rt = reader.begin()
        reader.execute(text("SELECT id FROM valuation_outputs LIMIT 1"))
        dt = ddl.begin()
        _bind(monkeypatch, migration, ddl)
        with pytest.raises(DBAPIError) as error:
            migration.upgrade()
        assert error.value.orig.sqlstate == '55P03'
        dt.rollback()
        rt.commit()
    with pg.begin() as conn:
        assert conn.execute(text("SELECT to_regprocedure('valuation_peer_rank_inputs_v1(json)')")).scalar() is None
        assert conn.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='valuation_outputs' AND column_name='peer_rank_inputs'")).scalar() == 0
        _bind(monkeypatch, migration, conn)
        migration.upgrade()
        assert len(backfill_batch(conn, 100)) == 5


def test_pg_empty_skip_locked_batch_is_not_completion(pg, monkeypatch):
    migration = _migration()
    with pg.begin() as conn:
        _bind(monkeypatch, migration, conn)
        migration.upgrade()
    with pg.connect() as blocker, pg.connect() as batch:
        blocked = blocker.begin()
        blocker.execute(text('SELECT id FROM valuation_outputs FOR UPDATE')).all()
        with batch.begin():
            assert backfill_batch(batch, 100) == []
            assert batch.execute(text('SELECT EXISTS (SELECT 1 FROM valuation_outputs WHERE peer_rank_inputs IS NULL)')).scalar() is True
        blocked.rollback()
    with pg.begin() as conn:
        assert len(backfill_batch(conn, 100)) == 5


def test_pg_rejects_conflicting_stored_design(pg, monkeypatch):
    from app.valuation.peer_rank_projection import FUNCTION_SQL
    migration = _migration()
    with pg.begin() as conn:
        conn.execute(text(FUNCTION_SQL))
        conn.execute(text("ALTER TABLE valuation_outputs ADD COLUMN peer_rank_inputs json GENERATED ALWAYS AS (valuation_peer_rank_inputs_v1(output_payload)) STORED"))
    with pg.connect() as conn:
        tx = conn.begin()
        _bind(monkeypatch, migration, conn)
        with pytest.raises(DBAPIError, match="not the online design"):
            migration.upgrade()
        tx.rollback()
