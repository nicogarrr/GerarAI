"""0123: indice de expresion (input_payload->>'ticker') para tracked_statuses
y equivalencia de la lectura ventana (ultima corrida por ticker)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from tests.test_alembic_chain import VERSIONS_DIR

_NOMBRE = "ix_workflow_runs_tracked_ticker"


def _sqlite_head(tmp_path, monkeypatch) -> sa.Engine:
    from app.core.config import get_settings

    url = f"sqlite:///{tmp_path}/mig0123.db"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
    command.upgrade(cfg, "head")
    get_settings.cache_clear()
    return sa.create_engine(url)


def test_0123_indice_existe_tras_upgrade_head_en_sqlite(tmp_path, monkeypatch) -> None:
    engine = _sqlite_head(tmp_path, monkeypatch)
    with engine.connect() as conn:
        # sqlite no refleja indices de expresion por el inspector: sqlite_master.
        nombres = {
            row[0]
            for row in conn.execute(
                sa.text("select name from sqlite_master where type='index'")
            )
        }
    assert _NOMBRE in nombres


def test_tracked_statuses_devuelve_solo_la_ultima_corrida_por_ticker() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models.entities import Base, Tenant, WorkflowRun
    from app.services.thesis_job_service import WORKFLOW_NAME
    from app.services.tracked_analysis import tracked_statuses

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add(Tenant(id=1, external_id="t"))
    base = datetime(2026, 10, 30, tzinfo=UTC)

    def run(ticker: str, offset_min: int, status: str) -> WorkflowRun:
        return WorkflowRun(
            tenant_id=1,
            workflow_name=WORKFLOW_NAME,
            execution_mode="deterministic",
            status=status,
            attempt=1,
            idempotency_key=f"{ticker}-{offset_min}",
            input_payload={"ticker": ticker},
            result_payload={"status": "ok"},
            created_at=base + timedelta(minutes=offset_min),
            updated_at=base + timedelta(minutes=offset_min),
        )

    # Dos corridas por ticker: la mas reciente (id mayor) es la que manda.
    db.add_all([
        run("AAPL", 1, "failed"),
        run("AAPL", 2, "succeeded"),
        run("MSFT", 1, "succeeded"),
        run("MSFT", 2, "failed"),
        # Ruido: otro workflow y otro tenant no se cuelan.
        WorkflowRun(
            tenant_id=1, workflow_name="otro", execution_mode="deterministic",
            status="succeeded", attempt=1, idempotency_key="otro-1",
            input_payload={"ticker": "AAPL"}, result_payload={},
            created_at=base + timedelta(minutes=99), updated_at=base,
        ),
    ])
    db.commit()
    db.info["tenant_id"] = 1
    out = tracked_statuses(db, ["AAPL", "MSFT"])
    assert out["AAPL"]["status"] == "succeeded"
    assert out["MSFT"]["status"] == "failed"
    assert set(out) == {"AAPL", "MSFT"}
