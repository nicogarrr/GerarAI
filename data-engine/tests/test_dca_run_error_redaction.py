"""El error de una ejecucion DCA se ensena en la watchlist: nunca con secretos.

``finish_run`` guardaba ``f"{type(exc).__name__}: {exc}"`` tal cual y
``run_payload`` lo devolvia a la API (``last_run.error``, el motivo por ticker y
``/dca-signals/manual-runs/{id}``). Un fallo de conexion trae el DSN con la
password o la URL del proveedor con ``?apikey=``. El mensaje se sigue mostrando
(test_dca_run_log lo exige), pero redactado.
"""
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import DcaEvaluationRun
from app.models.entities import Base
from app.services import dca_run_log

LEAK = (
    "OperationalError: connection to postgresql://gerarai:hunter2@10.0.0.7/prod failed; "
    "yahoo down https://example.test/q?symbol=A&apikey=SECRETKEY123 password=s3cr3t"
)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    db.info["tenant_id"] = 1
    return db


def test_finish_run_redacts_secrets_but_keeps_the_message():
    db = _db()
    row = DcaEvaluationRun(tenant_id=1, trigger="manual", status="running", started_at=datetime.now(UTC))
    db.add(row)
    db.commit()
    dca_run_log.finish_run(db, row, error=LEAK)
    db.refresh(row)
    for secret in ("hunter2", "SECRETKEY123", "s3cr3t"):
        assert secret not in row.error
    assert "yahoo down" in row.error and row.status == "error"
    payload = dca_run_log.run_payload(row)
    assert "hunter2" not in payload["error"] and "yahoo down" in payload["error"]


def test_run_payload_redacts_rows_stored_before_the_fix():
    row = DcaEvaluationRun(tenant_id=1, trigger="scheduler", status="error",
                           started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
                           tracked=0, evaluated=0, skipped_count=0, errors_count=0,
                           alerted_count=0, detail={}, error=LEAK[:300])
    payload = dca_run_log.run_payload(row)
    for secret in ("hunter2", "SECRETKEY123", "s3cr3t"):
        assert secret not in payload["error"]
    item = dca_run_log.item_evaluation("A", False, payload)
    assert item["status"] == "job_failed" and "hunter2" not in item["reason"]
