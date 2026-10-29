"""El error de una ejecucion DCA se ensena en la watchlist: solo un mensaje generico.

Decision de Nico (29-oct): el usuario ve «No se pudo completar la evaluacion
DCA. Reintenta mas tarde.» en ``last_run.error``, en el motivo por ticker y en
``/dca-signals/manual-runs/{id}``. El detalle tecnico (que puede traer el DSN con
la password o la URL con ``?apikey=``) va solo al log del servidor, redactado.
"""
import logging
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


def test_finish_run_shows_generic_message_and_logs_redacted_detail(caplog):
    db = _db()
    row = DcaEvaluationRun(tenant_id=1, trigger="manual", status="running", started_at=datetime.now(UTC))
    db.add(row)
    db.commit()
    with caplog.at_level(logging.ERROR, logger="app.services.dca_run_log"):
        dca_run_log.finish_run(db, row, error=LEAK)
    db.refresh(row)
    assert row.status == "error"
    assert row.error == dca_run_log.PUBLIC_RUN_ERROR
    payload = dca_run_log.run_payload(row)
    assert payload["error"] == "No se pudo completar la evaluación DCA. Reintenta más tarde."
    item = dca_run_log.item_evaluation("A", False, payload)
    assert item == {"status": "job_failed", "reason": dca_run_log.PUBLIC_RUN_ERROR}
    logged = caplog.text
    assert "yahoo down" in logged
    for secret in ("hunter2", "SECRETKEY123", "s3cr3t"):
        assert secret not in logged


def test_rows_stored_before_the_change_never_show_their_text():
    row = DcaEvaluationRun(tenant_id=1, trigger="scheduler", status="error",
                           started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
                           tracked=0, evaluated=0, skipped_count=0, errors_count=0,
                           alerted_count=0, detail={}, error="RuntimeError: yahoo down")
    payload = dca_run_log.run_payload(row)
    assert payload["error"] == dca_run_log.PUBLIC_RUN_ERROR
    item = dca_run_log.item_evaluation("A", False, payload)
    assert item["status"] == "job_failed" and "yahoo" not in item["reason"]


def test_ok_run_has_no_error():
    db = _db()
    row = DcaEvaluationRun(tenant_id=1, trigger="manual", status="running", started_at=datetime.now(UTC))
    db.add(row)
    db.commit()
    dca_run_log.finish_run(db, row, summary={"tracked": 1, "evaluated": 1})
    assert row.error is None and dca_run_log.run_payload(row)["error"] is None


def test_manual_status_endpoint_shows_generic_message():
    from app.api.routes import watchlist
    db = _db()
    row = DcaEvaluationRun(tenant_id=1, trigger="manual", status="error", started_at=datetime.now(UTC),
                           finished_at=datetime.now(UTC), detail={}, error="ValueError: bad history apikey=XYZ")
    db.add(row)
    db.commit()
    out = watchlist.manual_dca_status(row.id, db)
    assert out["status"] == "error" and out["error"] == dca_run_log.PUBLIC_RUN_ERROR
