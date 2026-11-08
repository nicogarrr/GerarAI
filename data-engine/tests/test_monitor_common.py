"""Nucleo compartido de los monitores SEC (app/services/monitor_common.py).

Hueco de cobertura: watermark en connector_states, registro de exito y manejo
del fallo fatal no tenian tests propios (los monitores concretos tienen los
suyos, de dominio). Contrato que se fija:

- una fila por (connector, tenant), creada si falta;
- exito: consecutive_errors a 0, acumulados en metadata_ y cursor = status;
- fatal: NUNCA llega una excepcion al actor; rollback previo (la sesion pudo
  quedar envenenada), consecutive_errors + 1 y last_error con secretos
  redactados;
- con public_reason, stats["errors"] lleva solo la razon constante (ese stats
  se sirve en la API y nada derivado de la excepcion puede viajar).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.models import Tenant
from app.models.entities import Base, ConnectorState
from app.services import monitor_common


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _tenant(db: Session) -> Tenant:
    tenant = Tenant(external_id="mon-tenant", name="M")
    db.add(tenant)
    db.commit()
    return tenant


def test_connector_state_creates_once_per_connector_and_tenant(db):
    tenant = _tenant(db)
    first = monitor_common.connector_state(db, tenant.id, "sec_form4")
    again = monitor_common.connector_state(db, tenant.id, "sec_form4")
    other = monitor_common.connector_state(db, tenant.id, "sec_13dg")
    assert first.id == again.id
    assert other.id != first.id
    rows = db.scalars(select(ConnectorState)).all()
    assert len(rows) == 2


def test_connector_state_separates_tenants_and_global(db):
    tenant = _tenant(db)
    own = monitor_common.connector_state(db, tenant.id, "sec_form4")
    global_state = monitor_common.connector_state(db, None, "sec_form4")
    assert own.id != global_state.id
    assert global_state.tenant_id is None


def test_record_success_accumulates_and_resets_errors(db):
    tenant = _tenant(db)
    state = monitor_common.connector_state(db, tenant.id, "sec_form4")
    state.consecutive_errors = 3
    state.last_error = "fallo previo"
    db.commit()
    stats = {"status": "ok", "filings_new": 4, "transactions_created": 9}
    monitor_common.record_success(
        db, state, stats, extra_totals={"transactions_created": "transactions_total"}
    )
    db.refresh(state)
    assert state.consecutive_errors == 0
    assert state.last_error is None
    assert state.cursor == "ok"
    assert state.last_success_at is not None
    meta = state.metadata_
    assert meta["runs"] == 1
    assert meta["filings_new_total"] == 4
    assert meta["transactions_total"] == 9
    assert meta["last_run"] == stats
    # Segunda corrida: acumula, no pisa.
    monitor_common.record_success(
        db,
        state,
        {"status": "ok", "filings_new": 2, "transactions_created": 1},
        extra_totals={"transactions_created": "transactions_total"},
    )
    db.refresh(state)
    assert state.metadata_["runs"] == 2
    assert state.metadata_["filings_new_total"] == 6
    assert state.metadata_["transactions_total"] == 10


def test_record_fatal_never_raises_and_counts(db):
    tenant = _tenant(db)
    tid = tenant.id
    stats = {"status": "running", "errors": [], "filings_new": 0}
    monitor_common.record_fatal(db, tid, "sec_form4", stats, RuntimeError("boom"))
    state = db.scalar(
        select(ConnectorState).where(
            ConnectorState.connector == "sec_form4",
            ConnectorState.tenant_id == tid,
        )
    )
    assert state is not None
    assert state.consecutive_errors == 1
    assert "RuntimeError" in state.last_error
    assert "boom" in state.last_error
    assert stats["status"] == "error"
    assert stats["errors"] == ["fatal: RuntimeError: boom"]
    assert state.metadata_["runs"] == 1
    # record_fatal muta el dict in-place (sin copiarlo); tras el commit el ORM
    # expira y devuelve una copia deserializada, asi que se compara contenido.
    assert state.metadata_["last_run"] == stats
    # Segundo fallo: el contador sigue subiendo.
    monitor_common.record_fatal(db, tenant.id, "sec_form4", stats, ValueError("otro"))
    db.refresh(state)
    assert state.consecutive_errors == 2


def test_record_fatal_redacts_secrets_in_last_error(db):
    tenant = _tenant(db)
    stats = {"status": "running", "errors": [], "filings_new": 0}
    monitor_common.record_fatal(
        db,
        tenant.id,
        "sec_form4",
        stats,
        RuntimeError("GET https://fondo.example/x?apikey=SUPERSECRETO123 fallo"),
    )
    state = db.scalar(
        select(ConnectorState).where(
            ConnectorState.connector == "sec_form4",
            ConnectorState.tenant_id == tenant.id,
        )
    )
    assert "SUPERSECRETO123" not in state.last_error
    assert "SUPERSECRETO123" not in str(state.metadata_["last_run"]["errors"])


def test_record_fatal_public_reason_hides_exception_from_served_stats(db):
    tenant = _tenant(db)
    stats = {"status": "running", "errors": [], "filings_new": 0}
    monitor_common.record_fatal(
        db,
        tenant.id,
        "sec_13dg",
        stats,
        RuntimeError("detalle interno que no debe viajar"),
        public_reason="fallo de ingesta",
    )
    # El stats (que ownership.scan sirve) solo lleva la razon constante...
    assert stats["errors"] == ["fatal: fallo de ingesta"]
    # ...y el detalle redactado queda en last_error (persistido para ops, no servido).
    state = db.scalar(
        select(ConnectorState).where(
            ConnectorState.connector == "sec_13dg",
            ConnectorState.tenant_id == tenant.id,
        )
    )
    assert "detalle interno" in state.last_error


def test_record_fatal_recovers_from_poisoned_session(db):
    """Un commit roto envenena la sesion: record_fatal hace rollback y sigue."""
    tenant = _tenant(db)
    tid = tenant.id  # capturado antes de envenenar: tras el flush fallido, recargar tenant.id lanzaria
    # Envenena la sesion con un INSERT que viola NOT NULL y deja el flush fallido.
    db.add(ConnectorState(tenant_id=tenant.id, connector=None))  # type: ignore[arg-type]
    try:
        db.flush()
    except Exception:
        pass  # sesion envenenada: cualquier commit lanzaria PendingRollbackError
    stats = {"status": "running", "errors": [], "filings_new": 0}
    monitor_common.record_fatal(db, tid, "sec_form4", stats, RuntimeError("boom"))
    state = db.scalar(
        select(ConnectorState).where(
            ConnectorState.connector == "sec_form4",
            ConnectorState.tenant_id == tid,
        )
    )
    assert state is not None and state.consecutive_errors == 1
