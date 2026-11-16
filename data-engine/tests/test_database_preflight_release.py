"""Regression: concurrent dependencies must not reserve the DB pool before endpoints run."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

import app.core.database as coredb
from app.models.entities import Base, Tenant


def test_concurrent_preflights_release_pool_and_preserve_context(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'admission.db'}", poolclass=QueuePool,
                           pool_size=2, max_overflow=0, pool_timeout=0.15,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(Tenant(external_id="pool-tenant", name="Pool", metadata_={"language": "en"}))
        session.commit()
    monkeypatch.setattr(coredb, "SessionLocal", factory)
    monkeypatch.setattr(coredb, "settings", SimpleNamespace(research_auth_required=True, is_production=False))
    import app.core.i18n as i18n
    monkeypatch.setattr(i18n, "get_settings", lambda: SimpleNamespace(i18n_generation_enabled=True))
    principal = SimpleNamespace(tenant_external_id="pool-tenant", user_id="pool-user", email=None)
    generators = [coredb.get_db(principal=principal, request=None) for _ in range(6)]
    try:
        # Keep every yielded dependency alive, as happens while its endpoint is queued.
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(next, generators))
        assert engine.pool.checkedout() == 0
        for session in results:
            assert not session.in_transaction()
            assert session.info["language"] == "en"
            assert session.info["user_id"] == "pool-user"
            assert session.info["tenant_id"] is not None
            assert session.scalar(select(Tenant).where(Tenant.id == session.info["tenant_id"])).external_id == "pool-tenant"
            session.rollback()
    finally:
        for generator in generators:
            generator.close()
        engine.dispose()


def test_preflight_commits_real_email_binding_and_keeps_tenant_query_scope(tmp_path, monkeypatch):
    from app.models import UserEmailBinding, WatchItem
    engine = create_engine(f"sqlite:///{tmp_path / 'email.db'}", poolclass=QueuePool,
                           pool_size=2, max_overflow=0, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        a = Tenant(external_id="email-a", metadata_={"language": "en"})
        b = Tenant(external_id="email-b")
        session.add_all([a, b])
        session.commit()
        aid, bid = a.id, b.id
        session.add_all([WatchItem(tenant_id=aid, symbol="AAA"), WatchItem(tenant_id=bid, symbol="BBB")])
        session.commit()
    monkeypatch.setattr(coredb, "SessionLocal", factory)
    monkeypatch.setattr(coredb, "settings", SimpleNamespace(research_auth_required=True, is_production=False))
    import app.core.i18n as i18n
    monkeypatch.setattr(i18n, "get_settings", lambda: SimpleNamespace(i18n_generation_enabled=True))
    request = SimpleNamespace(method="GET", url=SimpleNamespace(path="/api/read"), state=SimpleNamespace())
    generator = coredb.get_db(principal=SimpleNamespace(tenant_external_id="email-a", user_id="u", email="u@example.com"), request=request)
    try:
        session = next(generator)
        assert engine.pool.checkedout() == 0
        assert session.info["tenant_id"] == request.state.tenant_id == aid
        assert session.info["language"] == "en"
        assert session.info["user_email"] == "u@example.com"
        assert session.scalars(select(WatchItem.symbol)).all() == ["AAA"]
        session.rollback()
        with factory() as check:
            binding = check.scalar(select(UserEmailBinding).where(UserEmailBinding.tenant_id == aid))
            assert binding.address == "u@example.com"
            assert binding.user_id == "u"
    finally:
        generator.close()
        engine.dispose()
