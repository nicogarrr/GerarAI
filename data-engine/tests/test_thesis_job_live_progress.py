"""realqa-21: «Generar tesis» no mostraba ningun progreso.

En produccion (prueba real del 27/10) cada generacion tarda 47-63 s en el
worker (redactar ~30 s, persistir 8-14 s), pero las fases se escribian con
flush() dentro del SAVEPOINT y solo se confirmaban al final: el sondeo de la
UI no veia ninguna y mostraba «En cola» hasta que aparecia la tesis.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models.entities import WorkflowRun
from app.services import thesis_job_service as svc


def _run(status="running", result=None, steps=None, tracked=False):
    return SimpleNamespace(
        id=7,
        workflow_name=svc.WORKFLOW_NAME,
        status=status,
        input_payload={"ticker": "POOL", "force": True, "tracked": tracked},
        steps=steps or [],
        result_payload=result,
        error_class=None,
        error_message=None,
        attempt=1,
        created_at=datetime(2026, 10, 27, 12, 53, tzinfo=UTC),
        started_at=datetime(2026, 10, 27, 12, 53, 1, tzinfo=UTC),
        finished_at=None,
    )


LIVE = {
    "progress": {
        "attempt": 1,
        "started_at": "2026-10-27T12:53:01+00:00",
        "published_at": "2026-10-27T12:54:01+00:00",
        "phases": [
            {"name": "collect_evidence", "status": "succeeded", "started_at": "a", "finished_at": "b"},
            {"name": "build_fundamental_model", "status": "succeeded", "started_at": "b", "finished_at": "c"},
            {"name": "compose_thesis", "status": "running", "started_at": "c", "finished_at": None},
        ]
    }
}


def test_job_payload_muestra_la_fase_en_curso_publicada_por_el_worker():
    body = svc.job_payload(_run(result=LIVE))
    assert body["current_phase"] == "compose_thesis"
    assert [p["name"] for p in body["phases"]] == ["collect_evidence", "build_fundamental_model", "compose_thesis"]
    assert body["total_phases"] == 7
    # El progreso no se presenta como resultado.
    assert body["result"] is None


def test_total_de_fases_incluye_refresco_sec_si_tracked():
    assert svc.job_payload(_run(result=LIVE, tracked=True))["total_phases"] == 8


def test_un_run_terminado_ignora_el_progreso_en_vivo():
    failed = svc.job_payload(_run(status="failed", result=LIVE))
    assert failed["phases"] == [] and failed["current_phase"] is None
    assert failed["result"] is None
    ok = svc.job_payload(_run(status="succeeded", result={"thesis_version_id": 3, "version": 2, "status": "draft"}))
    assert ok["result"]["version"] == 2


def test_filas_terminales_confirmadas_mandan_sobre_el_progreso_en_vivo():
    step = SimpleNamespace(step_name="persist_thesis", status="succeeded", position=7, attempt=1, started_at=None, finished_at=None)
    body = svc.job_payload(_run(status="succeeded", result=LIVE, steps=[step]))
    assert [p["name"] for p in body["phases"]] == ["persist_thesis"]


def test_publicar_progreso_solo_toca_el_intento_vivo():
    init_db()
    with SessionLocal() as db:
        run = WorkflowRun(workflow_name=svc.WORKFLOW_NAME, status="running", input_payload={"ticker": "ZPRG"}, attempt=2, started_at=datetime(2026, 10, 27, 12, 53, 1, tzinfo=UTC))
        db.add(run)
        db.commit()
        run_id = run.id
    phases = [{"name": "collect_evidence", "status": "running", "started_at": "x", "finished_at": None}]
    # Un intento cercado (attempt viejo) no escribe.
    svc._publish_live_progress(run_id, 1, datetime(2026, 10, 27, 12, 53, 1, tzinfo=UTC), phases)
    with SessionLocal() as db:
        assert db.scalar(select(WorkflowRun.result_payload).where(WorkflowRun.id == run_id)) is None
    svc._publish_live_progress(run_id, 2, datetime(2026, 10, 27, 12, 53, 1, tzinfo=UTC), phases)
    with SessionLocal() as db:
        row = db.get(WorkflowRun, run_id)
        assert row is not None
        assert row.result_payload["progress"]["phases"] == phases
        assert row.result_payload["progress"]["attempt"] == 2
        body = svc.job_payload(row)
        assert body["current_phase"] == "collect_evidence"
        db.delete(row)
        db.commit()


def test_publicar_progreso_nunca_lanza(monkeypatch):
    def boom():
        raise RuntimeError("db caída")

    monkeypatch.setattr(svc, "SessionLocal", boom)
    svc._publish_live_progress(1, 1, datetime.now(UTC), [])


def test_sqlite_no_publica_en_paralelo_postgres_si():
    assert svc._live_progress_supported(SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))) is False
    assert svc._live_progress_supported(SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))) is True


def test_tracked_refresh_confirmado_no_oculta_fases_nuevas():
    step = SimpleNamespace(step_name="refresh_sec", status="running", position=1, attempt=1, started_at=None, finished_at=None)
    body = svc.job_payload(_run(result=LIVE, steps=[step], tracked=True))
    assert body["current_phase"] == "compose_thesis"
    assert body["total_phases"] == 8


def test_reintento_no_muestra_pasos_del_intento_anterior():
    from copy import deepcopy

    old = SimpleNamespace(step_name="run_valuation", status="retrying", position=3, attempt=1, started_at=None, finished_at=None)
    progress = deepcopy(LIVE)
    progress["progress"]["attempt"] = 2
    run = _run(result=progress, steps=[old])
    run.attempt = 2
    assert svc.job_payload(run)["current_phase"] == "compose_thesis"
    run.result_payload = None
    assert svc.job_payload(run)["phases"] == []


def test_progreso_viejo_sin_identidad_o_de_otro_inicio_no_se_reproduce():
    from copy import deepcopy

    for key, value in [("attempt", 0), ("started_at", "2026-10-27T12:52:01+00:00"), ("published_at", "2026-10-27T12:52:01+00:00"), ("published_at", "2999-01-01T00:00:00+00:00")]:
        progress = deepcopy(LIVE)
        progress["progress"][key] = value
        assert svc.job_payload(_run(result=progress))["current_phase"] is None
    assert svc.job_payload(_run(result={"progress": {"phases": LIVE["progress"]["phases"]}}))["phases"] == []


def test_estado_terminal_o_cancelado_nunca_usa_progreso_vivo():
    for status in ("failed", "succeeded", "cancelled", "retrying", "queued"):
        assert svc.job_payload(_run(status=status, result=LIVE))["current_phase"] is None


def test_publicacion_cercada_por_inicio_y_terminal_no_sobrescribe():
    init_db()
    started = datetime(2026, 10, 27, 12, 53, 1, tzinfo=UTC)
    with SessionLocal() as db:
        run = WorkflowRun(workflow_name=svc.WORKFLOW_NAME, status="running", input_payload={}, attempt=1, started_at=started)
        db.add(run)
        db.commit()
        run_id = run.id
    svc._publish_live_progress(run_id, 1, datetime(2026, 10, 27, 12, 52, 1, tzinfo=UTC), [])
    with SessionLocal() as db:
        row = db.get(WorkflowRun, run_id)
        assert row.result_payload is None
        row.status = "succeeded"
        row.result_payload = {"version": 3}
        db.commit()
    svc._publish_live_progress(run_id, 1, started, [])
    with SessionLocal() as db:
        row = db.get(WorkflowRun, run_id)
        assert row.result_payload == {"version": 3}
        db.delete(row)
        db.commit()
