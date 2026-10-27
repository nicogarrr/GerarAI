"""Un fallo persistente ANTES del reclamo debe consumir intentos y terminar."""

import types
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.models import Tenant
from app.models.entities import Base, WorkflowRun
from app.services import thesis_job_service as j


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(j, "SessionLocal", factory)
    monkeypatch.setattr(
        j, "get_settings", lambda: types.SimpleNamespace(research_auth_required=False, is_production=False)
    )
    return factory


def _seed(factory, *, status, attempt, hours_ago):
    with factory() as db:
        tenant = Tenant(external_id="ext", name="t", status="active")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        run = WorkflowRun(
            workflow_name=j.WORKFLOW_NAME, status=status, tenant_id=tenant.id, attempt=attempt,
            input_payload={"ticker": "X", "force": True, "tenant_id": tenant.id, "user_id": "u"},
            started_at=datetime.now(UTC) - timedelta(hours=hours_ago) if hours_ago is not None else None,
        )
        db.add(run)
        db.commit()
        return run.id


def _state(factory, rid):
    with factory() as db:
        row = db.get(WorkflowRun, rid, execution_options={"include_all_tenants": True})
        return row.status, row.attempt, row.error_class


def _break_config(monkeypatch, exc):
    import app.services.tenant_llm_settings_service as svc

    def boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr(svc, "load_config_for_tenant", boom)


def _fake_generation(monkeypatch, calls):
    import sys

    class Fake:
        def generate(self, db, ticker, **kwargs):
            calls.append(ticker)
            return types.SimpleNamespace(id=1, version=1, status="final")

    monkeypatch.setitem(sys.modules, "app.services.thesis_service", types.SimpleNamespace(ThesisService=Fake))
    monkeypatch.setitem(
        sys.modules, "app.services.company_enrichment_service",
        types.SimpleNamespace(ensure_company_stub=lambda *a: None),
    )
    monkeypatch.setattr(j, "build_run_guard", lambda *a, **k: None)


def test_persistent_transient_failure_from_expired_lease_follows_normal_attempt_count(env, monkeypatch):
    rid = _seed(env, status="running", attempt=1, hours_ago=7)  # lease vencido
    _break_config(monkeypatch, OperationalError("select", {}, Exception("db down")))
    states = []
    for _ in range(2):
        with pytest.raises(OperationalError):
            j.run_thesis_job(rid)
        states.append(_state(env, rid))
    # Igual que un intento reclamado que falla: 2 (retrying) y luego 3 = MAX (failed).
    assert [s[:2] for s in states] == [("retrying", 2), ("failed", j.MAX_ATTEMPTS)]
    j.run_thesis_job(rid)  # ya terminal: se descarta
    assert _state(env, rid)[:2] == ("failed", j.MAX_ATTEMPTS)


def test_persistent_transient_failure_from_queued_uses_all_attempts_once(env, monkeypatch):
    rid = _seed(env, status="queued", attempt=1, hours_ago=None)
    _break_config(monkeypatch, OperationalError("select", {}, Exception("db down")))
    states = []
    for _ in range(j.MAX_ATTEMPTS):
        with pytest.raises(OperationalError):
            j.run_thesis_job(rid)
        states.append(_state(env, rid)[:2])
    assert states == [("retrying", 1), ("retrying", 2), ("failed", 3)]


def test_config_recovers_after_preclaim_failure_runs_next_attempt_not_skipping(env, monkeypatch):
    import app.services.tenant_llm_settings_service as svc

    calls: list = []
    _fake_generation(monkeypatch, calls)
    rid = _seed(env, status="queued", attempt=1, hours_ago=None)
    _break_config(monkeypatch, OperationalError("select", {}, Exception("db down")))
    with pytest.raises(OperationalError):
        j.run_thesis_job(rid)
    assert _state(env, rid)[:2] == ("retrying", 1)
    monkeypatch.setattr(svc, "load_config_for_tenant", lambda db, tenant_id: None)
    monkeypatch.setattr("app.llm.tenant_config.tenant_llm_config_scope", lambda cfg: __import__("contextlib").nullcontext())
    j.run_thesis_job(rid)
    assert len(calls) == 1
    assert _state(env, rid)[:2] == ("succeeded", 2)  # intento 2, sin doble consumo


def test_config_recovers_from_expired_lease_preclaim_failure_runs_attempt_three_at_most(env, monkeypatch):
    import app.services.tenant_llm_settings_service as svc

    calls: list = []
    _fake_generation(monkeypatch, calls)
    rid = _seed(env, status="running", attempt=1, hours_ago=7)
    _break_config(monkeypatch, OperationalError("select", {}, Exception("db down")))
    with pytest.raises(OperationalError):
        j.run_thesis_job(rid)
    assert _state(env, rid)[:2] == ("retrying", 2)
    monkeypatch.setattr(svc, "load_config_for_tenant", lambda db, tenant_id: None)
    monkeypatch.setattr("app.llm.tenant_config.tenant_llm_config_scope", lambda cfg: __import__("contextlib").nullcontext())
    j.run_thesis_job(rid)
    assert len(calls) == 1
    assert _state(env, rid)[:2] == ("succeeded", 3)


def test_permanent_preclaim_failure_is_terminal_at_once(env, monkeypatch):
    rid = _seed(env, status="queued", attempt=1, hours_ago=None)
    _break_config(monkeypatch, RuntimeError("config invalid"))
    with pytest.raises(RuntimeError):
        j.run_thesis_job(rid)
    assert _state(env, rid) == ("failed", 1, "RuntimeError")  # queued: intento 1 fallido


def test_preclaim_failure_does_not_overwrite_a_live_owner(env, monkeypatch):
    rid = _seed(env, status="queued", attempt=1, hours_ago=None)
    _break_config(monkeypatch, OperationalError("select", {}, Exception("db down")))
    original = j._record_preclaim_failure

    def other_delivery_claims_first(db, run_id, exc):
        with env() as other:
            row = other.get(WorkflowRun, run_id, execution_options={"include_all_tenants": True})
            row.status, row.attempt, row.started_at = "running", 2, datetime.now(UTC)
            other.commit()
        original(db, run_id, exc)

    monkeypatch.setattr(j, "_record_preclaim_failure", other_delivery_claims_first)
    with pytest.raises(OperationalError):
        j.run_thesis_job(rid)
    assert _state(env, rid)[:2] == ("running", 2)
