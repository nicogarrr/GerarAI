import logging

from sqlalchemy import create_engine, text

from app.core import pool_probe
from app.core.config import Settings


def test_empty_model_overrides_env_is_an_empty_dict(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_OVERRIDES", "")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    assert Settings().llm_model_overrides == {}


def test_json_model_overrides_env_still_parses(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_OVERRIDES", '{"a": "b"}')
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    assert Settings().llm_model_overrides == {"a": "b"}


def test_pool_probe_reports_outstanding_connections(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(pool_probe, "_INSTALLED", False)
    monkeypatch.setattr(pool_probe, "_OUT", {})
    monkeypatch.setattr(pool_probe, "_LAST_DUMP", 0.0)
    engine = create_engine(f"sqlite:///{tmp_path}/p.db", connect_args={"check_same_thread": False})
    pool_probe.install(engine, threshold=2, min_interval_s=0)
    held = [engine.connect(), engine.connect()]
    with caplog.at_level(logging.WARNING, logger=pool_probe.logger.name):
        held.append(engine.connect())
    assert any("db pool pressure" in r.getMessage() for r in caplog.records)
    message = " ".join(r.getMessage() for r in caplog.records)
    assert "SELECT" not in message
    assert len(pool_probe.outstanding()) == 3
    for conn in held:
        conn.execute(text("select 1"))
        conn.close()
    assert pool_probe.outstanding() == []


def test_pool_probe_forgets_invalidated_and_closed_connections(monkeypatch, tmp_path):
    monkeypatch.setattr(pool_probe, "_INSTALLED", False)
    monkeypatch.setattr(pool_probe, "_OUT", {})
    engine = create_engine(f"sqlite:///{tmp_path / 'p.db'}")
    pool_probe.install(engine, threshold=99)
    a = engine.connect()
    b = engine.connect()
    assert len(pool_probe.outstanding()) == 2
    a.invalidate()
    a.close()
    b.close()
    assert pool_probe.outstanding() == []


def test_slow_request_middleware_logs_only_slow_requests(caplog):
    import asyncio

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def run(threshold):
        mw = pool_probe.SlowRequestMiddleware(app, threshold_s=threshold, pool_out=lambda: 7)
        scope = {"type": "http", "method": "GET", "path": "/x", "query_string": b"token=secret"}
        await mw(scope, None, lambda m: asyncio.sleep(0))

    with caplog.at_level(logging.WARNING, logger=pool_probe.logger.name):
        asyncio.run(run(60))
        assert "slow request" not in caplog.text
        asyncio.run(run(0))
    assert "slow request: GET /x status=200" in caplog.text
    assert "pool_checkedout=7" in caplog.text
    assert "secret" not in caplog.text


def test_pool_configuration_defaults():
    """VAL-PERF-007: connection pool configured with 10-20 connections."""
    settings = Settings(database_url="postgresql://user:pass@localhost/db")
    assert settings.db_pool_size == 10
    assert settings.db_max_overflow == 10
    assert settings.db_pool_timeout == 30.0
    assert settings.db_pool_recycle == 3600
    # Total connections: pool_size + max_overflow = 10 + 10 = 20


def test_pool_kwargs_applied_only_for_postgres():
    """Pool parameters are only applied to PostgreSQL, not SQLite."""
    from app.core.database import _engine_pool_kwargs

    settings = Settings(database_url="sqlite:///test.db")
    
    # SQLite should get empty dict (no pool params)
    sqlite_kwargs = _engine_pool_kwargs("sqlite:///test.db", settings)
    assert sqlite_kwargs == {}
    
    # PostgreSQL should get pool params
    pg_kwargs = _engine_pool_kwargs("postgresql://user:pass@localhost/db", settings)
    assert pg_kwargs["pool_size"] == 10
    assert pg_kwargs["max_overflow"] == 10
    assert pg_kwargs["pool_timeout"] == 30.0
    assert pg_kwargs["pool_recycle"] == 3600
    
    # PostgreSQL with driver suffix
    pg_psycopg_kwargs = _engine_pool_kwargs("postgresql+psycopg://user:pass@localhost/db", settings)
    assert pg_psycopg_kwargs["pool_size"] == 10


def test_pool_pre_ping_enabled():
    """Pool pre-ping is enabled to detect stale connections."""
    from app.core.database import engine
    
    # Check that pool_pre_ping is set on the engine
    assert engine.pool._pre_ping is True
