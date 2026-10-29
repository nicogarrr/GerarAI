"""Offline regressions: durable thesis jobs and settings read failures fail closed."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.llm.tenant_config import current_tenant_llm_config
from app.models import Tenant, TenantLLMSettings
from app.seed import seed
from app.services import thesis_job_service as jobs
from app.workers.tenant_llm_middleware import TenantLLMSettingsMiddleware, _tenant_id_from_message


@pytest.fixture(autouse=True)
def cleanup_synthetic_rows():
    yield
    from sqlalchemy import inspect as sa_inspect

    from app.core.database import engine
    from app.models.entities import WorkflowRun, WorkflowStepRun

    # Con xdist (--dist load) un worker puede recibir solo tests de este
    # modulo que no llaman a init_db(): su sqlite por proceso no tiene
    # esquema y el SELECT de limpieza fallaba con "no such table: tenants".
    if not sa_inspect(engine).has_table("tenants"):
        return
    with SessionLocal() as db:
        tids = list(db.scalars(select(Tenant.id).where(Tenant.external_id.like("audit-%"))))
        if tids:
            db.execute(delete(WorkflowStepRun).where(WorkflowStepRun.tenant_id.in_(tids)))
            db.execute(delete(WorkflowRun).where(WorkflowRun.tenant_id.in_(tids)))
            db.execute(delete(TenantLLMSettings).where(TenantLLMSettings.tenant_id.in_(tids)))
            db.execute(delete(Tenant).where(Tenant.id.in_(tids)))
            db.commit()


@pytest.mark.parametrize("generation_fails", [False, True])
def test_async_thesis_disabled_tenant_is_bound(monkeypatch, generation_fails):
    init_db()
    seed()
    import app.workers.dramatiq_app as workers
    from app.services.thesis_service import ThesisService

    monkeypatch.setattr(workers.generate_thesis_job, "send", lambda *a, **k: None)
    seen = []

    def generate(self, db, ticker, **kwargs):
        from app.core.config import Settings
        from app.llm.chat_provider import create_background_llm_provider
        from app.llm.factory import create_llm_provider
        from app.llm.thesis_go import create_thesis_narrative_provider

        synthetic = Settings(
            _env_file=None,
            app_env="test",
            llm_enabled=True,
            llm_provider="opencode-go",
            opencode_go_api_key="synthetic-platform-key",
        )
        names = [
            f(synthetic).name
            for f in (create_llm_provider, create_background_llm_provider, create_thesis_narrative_provider)
        ]
        assert names == ["disabled"] * 3
        seen.append((db.info.get("tenant_id"), current_tenant_llm_config()))
        if generation_fails:
            raise ValueError("synthetic generation failure")
        return SimpleNamespace(id=991, version=1, status="final")

    monkeypatch.setattr(ThesisService, "generate", generate)
    with SessionLocal() as db:
        t = Tenant(external_id="audit-" + uuid4().hex, name="synthetic disabled tenant")
        db.add(t)
        db.commit()
        tid = t.id
        db.info.update(tenant_id=tid, user_id="synthetic-user")
        db.add(TenantLLMSettings(tenant_id=tid, provider="openai", model="gpt-4.1-mini", enabled=False))
        db.commit()
        r, _ = jobs.enqueue_generation(db, "AAPL", False)
        rid = r.id
    msg = SimpleNamespace(actor_name="generate_thesis_job", args=(rid,), kwargs={}, options={})
    assert _tenant_id_from_message(workers.broker, msg) is None
    middleware = TenantLLMSettingsMiddleware()
    middleware.before_process_message(workers.broker, msg)
    try:
        if generation_fails:
            with pytest.raises(ValueError, match="synthetic generation failure"):
                jobs.run_thesis_job(rid)
        else:
            jobs.run_thesis_job(rid)
        # The job itself restores its scope, before broker middleware cleanup.
        assert current_tenant_llm_config() is None
    finally:
        middleware.after_process_message(workers.broker, msg)
    assert len(seen) == 1 and seen[0][0] == tid
    assert seen[0][1] is not None and seen[0][1].enabled is False
    assert current_tenant_llm_config() is None


def test_db_read_failure_returns_disabled_context(monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.core.config import Settings
    from app.llm.factory import create_llm_provider
    from app.llm.tenant_config import tenant_llm_config_scope
    from app.services import tenant_llm_settings_service as svc

    def fail(*a, **k):
        raise OperationalError("synthetic-settings-read", {}, Exception("synthetic failure"))

    monkeypatch.setattr(svc, "read_tenant_row", fail)
    c = svc.load_config_for_tenant(object(), 1)
    s = Settings(
        _env_file=None,
        app_env="test",
        llm_enabled=True,
        llm_provider="opencode-go",
        opencode_go_api_key="synthetic-platform-key",
    )
    with tenant_llm_config_scope(c):
        p = create_llm_provider(s)
    assert c is not None and p.name == "disabled"
    assert p.reason == "tenant_llm_settings_unavailable"


def test_normal_actor_binds_disabled_tenant_and_resets(monkeypatch):
    from app.core.config import Settings
    from app.llm.chat_provider import create_background_llm_provider

    init_db()
    import app.workers.dramatiq_app as workers

    s = Settings(
        _env_file=None,
        app_env="test",
        llm_enabled=True,
        llm_provider="opencode-go",
        opencode_go_api_key="synthetic-platform-key",
    )
    mids = []
    with SessionLocal() as db:
        for tag in ("a", "b"):
            t = Tenant(external_id="audit-" + tag + uuid4().hex, name="synthetic " + tag)
            db.add(t)
            db.commit()
            db.add(
                TenantLLMSettings(
                    tenant_id=t.id,
                    provider="openai",
                    model="gpt-4.1-mini" if tag == "a" else "gpt-4.1",
                    enabled=False,
                )
            )
            db.commit()
            mids.append(t.id)
    mw = TenantLLMSettingsMiddleware()
    for index, tid in enumerate(mids):
        msg = SimpleNamespace(actor_name="process_document", args=(), kwargs={"tenant_id": tid}, options={})
        mw.before_process_message(workers.broker, msg)
        try:
            assert current_tenant_llm_config() is not None
            assert current_tenant_llm_config().enabled is False
            assert current_tenant_llm_config().model == ("gpt-4.1-mini" if index == 0 else "gpt-4.1")
            assert create_background_llm_provider(s).name == "disabled"
        finally:
            mw.after_process_message(workers.broker, msg)
        assert current_tenant_llm_config() is None
    # Zero is an int, not confused with absence by extraction.
    assert _tenant_id_from_message(workers.broker, SimpleNamespace(kwargs={"tenant_id": 0})) == 0


def test_confirmed_absence_keeps_platform_default(monkeypatch):
    from app.services import tenant_llm_settings_service as svc

    monkeypatch.setattr(svc, "read_tenant_row", lambda *a, **k: None)
    assert svc.load_config_for_tenant(object(), 1) is None
