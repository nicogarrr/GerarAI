"""Un sondeo de /dca-signals/manual-runs/{id} nunca debe ver "ok" sin resumen.

run_manual_job confirmaba ``status='ok'`` en ``finish_run`` (que ademas
reescribia ``detail`` entero) y solo despues, en un segundo commit, guardaba
``detail['summary']``. Un sondeo entre ambos commits recibia ``status: ok``
con ``summary: null`` y DcaEvaluateButton mostraba «No se pudieron evaluar
las señales DCA» tras una evaluacion correcta.
"""
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import DcaEvaluationRun
from app.models.entities import Base
from app.services import dca_manual_job


class Gate:
    def get(self, key): return b"token"
    def eval(self, script, *args): return 1
    def close(self): pass


def test_ok_status_is_committed_together_with_its_summary(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.info["tenant_id"] = 1
        row = DcaEvaluationRun(tenant_id=1, trigger="manual", status="queued",
            started_at=datetime.now(UTC), detail={"requested_symbols": ["A"], "pending_remaining": 2})
        db.add(row)
        db.commit()
        monkeypatch.setattr(dca_manual_job, "redis_client", lambda: Gate())
        monkeypatch.setattr("app.services.dca_signal_service.evaluate_watchlist",
            lambda db, *, symbols: dict(tracked=1, evaluated=1, alerted=[], skipped=[], errors=[],
                                        alerts_enabled=False, params_version="v1"))
        committed = []

        @event.listens_for(db, "after_commit")
        def snapshot(session):
            with engine.connect() as conn:
                status, detail = conn.exec_driver_sql(
                    "SELECT status, detail FROM dca_evaluation_runs WHERE id = ?", (row.id,)).one()
            committed.append((status, detail))

        assert dca_manual_job.run_manual_job(db, row.id, "token")["status"] == "ok"
        oks = [detail for status, detail in committed if status == "ok"]
        assert oks, committed
        # La primera vez que otra conexion lee "ok", el resumen ya esta.
        assert '"summary"' in oks[0], committed
        assert '"requested_symbols"' in oks[0]
    engine.dispose()
