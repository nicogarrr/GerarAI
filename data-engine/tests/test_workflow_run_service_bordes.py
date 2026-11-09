"""workflow_run_service: bordes del sobre de corridas con SQLite real.

Cubierto aqui:
- _safe_commit: commit que lanza -> warning + rollback + False (doble de
  Session.commit que primero inserta la fila "rival" por otra sesion y luego
  falla, para ejercitar honestamente la carrera de begin_run).
- record_step en fallo con tracer None (sobre replayed) y con token ya
  consumido (tras finish): ambas salidas del bloque tracer.
- finish dos veces: la segunda encuentra _tracer_token None.
- finish/fail con sobre replayed (tracer None) y fail con tracer activo.
- begin_run: sin idempotency_key; replay de una corrida "running" (replayed
  True sin nueva fila); reintento de corrida fallida con tenant (reutiliza la
  fila, sube attempt, limpia error y resultado); carrera en el commit inicial
  (la otra entrega inserta la fila: recupera y devuelve replayed segun el
  estado de la fila rival).

No se prueba aqui: el tracer real contra Langfuse (shadow tracing ya tiene
test_shadow_tracing.py; aqui el tracer es el objeto inerte por defecto, sin
red) ni la rama `raced is None` de la carrera (devolveria un run sin id:
estado degradado ya defendido por el comentario del codigo).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Tenant, WorkflowRun, WorkflowStepRun
from app.services import tracing
from app.services.workflow_run_service import _safe_commit, begin_run


@pytest.fixture(autouse=True)
def _tracing_inerte_y_aislado(monkeypatch):
    # Tracing explicitamente inerte: no depende de las flags del entorno.
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    # Aisla el ContextVar global: un begin_run sin finish/fail no puede dejar
    # _current_tracer apuntando al tracer de este test.
    token = tracing.set_current_tracer(None)
    yield
    tracing.reset_current_tracer(token)
    get_settings.cache_clear()


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        session.info["tenant_id"] = None
        yield session


def test_safe_commit_devuelve_false_tras_excepcion(db: Session, monkeypatch):
    def _commit_roto():
        raise RuntimeError("commit roto")

    monkeypatch.setattr(db, "commit", _commit_roto)
    db.add(WorkflowRun(workflow_name="WF", status="running"))

    assert _safe_commit(db, "prueba") is False
    # Tras el rollback la sesion queda usable y sin la fila.
    assert db.query(WorkflowRun).count() == 0


def test_begin_run_sin_clave_no_busca_replay(db: Session):
    env = begin_run(db, "WF")

    assert env.replayed is False
    assert env.run.idempotency_key is None
    assert env.run.status == "running"
    assert db.query(WorkflowRun).count() == 1


def test_begin_run_replay_de_corrida_running_no_duplica(db: Session):
    primera = begin_run(db, "WF", idempotency_key="k-run")
    assert primera.replayed is False

    segunda = begin_run(db, "WF", idempotency_key="k-run")

    assert segunda.replayed is True
    assert segunda.run.id == primera.run.id
    assert segunda.run.status == "running"
    assert db.query(WorkflowRun).count() == 1


def test_begin_run_reintenta_fallida_con_tenant_reusando_fila(db: Session):
    tenant = Tenant(external_id="t-retry", name="t-retry")
    db.add(tenant)
    db.commit()
    db.info["tenant_id"] = tenant.id

    primera = begin_run(db, "WF", idempotency_key="k-fail")
    primera.fail(ValueError("boom"))
    run_id = primera.run.id
    assert primera.run.status == "failed"
    assert primera.run.error_class == "ValueError"

    # tenant_id explicito: salta el lookup en db.info (rama 167->172).
    segunda = begin_run(
        db, "WF", idempotency_key="k-fail", input_payload={"n": 1},
        tenant_id=tenant.id,
    )

    assert segunda.replayed is False
    assert segunda.run.id == run_id
    assert db.query(WorkflowRun).count() == 1
    assert segunda.run.status == "running"
    assert segunda.run.attempt == 2
    assert segunda.run.error_class is None
    assert segunda.run.error_message is None
    assert segunda.run.result_payload is None
    assert segunda.run.finished_at is None
    assert segunda.run.input_payload == {"n": 1}
    assert segunda.run.started_at is not None


def test_carrera_en_commit_inicial_recupera_fila_rival(
    db: Session, engine, monkeypatch
):
    # La "otra entrega" inserta la fila entre el lookup de replay y nuestro
    # commit: el doble de commit materializa esa carrera y luego falla.
    def _commit_carrera():
        with Session(engine) as otra:
            otra.add(
                WorkflowRun(
                    workflow_name="WF", idempotency_key="k-race",
                    status="running",
                )
            )
            otra.commit()
        raise RuntimeError("commit perdedor de la carrera")

    monkeypatch.setattr(db, "commit", _commit_carrera)

    env = begin_run(db, "WF", idempotency_key="k-race")

    # La fila rival sigue "running": no hay replay de resultado.
    assert env.replayed is False
    assert env.run.status == "running"
    assert db.query(WorkflowRun).count() == 1


def test_carrera_en_commit_inicial_replay_si_rival_termino(
    db: Session, engine, monkeypatch
):
    def _commit_carrera():
        with Session(engine) as otra:
            otra.add(
                WorkflowRun(
                    workflow_name="WF", idempotency_key="k-race2",
                    status="succeeded",
                )
            )
            otra.commit()
        raise RuntimeError("commit perdedor de la carrera")

    monkeypatch.setattr(db, "commit", _commit_carrera)

    env = begin_run(db, "WF", idempotency_key="k-race2")

    assert env.replayed is True
    assert env.run.status == "succeeded"
    assert db.query(WorkflowRun).count() == 1


def test_record_step_fallo_con_tracer_none(db: Session):
    env = begin_run(db, "WF", idempotency_key="k-ok")
    env.finish({"ok": True})
    # Sobre replayed: tracer es None y no toca tracing.
    replay = begin_run(db, "WF", idempotency_key="k-ok")
    assert replay.tracer is None

    def _handler_roto():
        raise KeyError("paso roto")

    with pytest.raises(KeyError):
        replay.record_step(1, "paso", _handler_roto)

    assert replay.run.status == "failed"
    assert replay.run.error_class == "KeyError"
    paso = db.query(WorkflowStepRun).one()
    assert paso.status == "failed"
    # Produccion guarda str(exc)[:1000]; str(KeyError) incluye comillas.
    assert paso.error_message == str(KeyError("paso roto"))
    assert paso.finished_at is not None


def test_record_step_fallo_tras_finish_consumido_token(db: Session):
    env = begin_run(db, "WF")
    assert env.tracer is not None
    env.finish({"ok": True})
    # finish consumio el token; el fallo posterior no debe resetear de nuevo.
    assert env._tracer_token is None

    def _handler_roto():
        raise RuntimeError("tras finish")

    with pytest.raises(RuntimeError):
        env.record_step(1, "paso", _handler_roto)

    assert env.run.status == "failed"
    assert env.run.error_class == "RuntimeError"


def test_finish_dos_veces_no_resetea_token_ya_consumido(db: Session):
    env = begin_run(db, "WF", idempotency_key="k-f2")
    env.finish({"ok": True})
    assert env._tracer_token is None

    env.finish({"ok": 2})

    assert env.run.status == "succeeded"
    assert env.run.result_payload == {"ok": 2}

    # Sobre replayed (tracer None): finish no toca tracing (rama 129->134).
    replay = begin_run(db, "WF", idempotency_key="k-f2")
    assert replay.tracer is None
    replay.finish({"ok": 3})
    assert replay.run.result_payload == {"ok": 3}


def test_fail_con_tracer_activo_y_con_tracer_none(db: Session):
    env = begin_run(db, "WF", idempotency_key="k-f1")
    assert env.tracer is not None
    env.fail(ValueError("fallo directo"))
    assert env.run.status == "failed"
    assert env.run.error_class == "ValueError"
    assert env.run.error_message == "fallo directo"
    assert env._tracer_token is None

    # Sobre replayed (tracer None) la misma ruta no toca tracing.
    env.finish({"ok": True})
    replay = begin_run(db, "WF", idempotency_key="k-f1")
    replay.fail(RuntimeError("otro"))
    assert replay.run.status == "failed"
    assert replay.run.error_class == "RuntimeError"

    # fail con tracer activo pero token ya consumido (rama 146->exit).
    env2 = begin_run(db, "WF2")
    env2.fail(ValueError("primero"))
    assert env2._tracer_token is None
    env2.fail(ValueError("segundo"))
    assert env2.run.error_message == "segundo"
