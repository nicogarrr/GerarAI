"""Carreras: registro de fuentes RAG y congelado mensual de ProPicks deben ser idempotentes."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Company, Tenant
from app.models.propick_snapshot import PropickSnapshot

N = 6


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    with maker() as s:
        s.add(Tenant(id=1, external_id="race-1"))
        s.commit()
    yield maker
    engine.dispose()


def _race(factory, work, n=N):
    out: list = [None] * n

    def run(i):
        with factory() as s:
            s.info["tenant_id"] = 1
            try:
                out[i] = work(s)
            except Exception as exc:  # noqa: BLE001
                out[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return out


def test_concurrent_knowledge_source_registration_is_idempotent(factory, tmp_path):
    """Misma subida en paralelo: una crea, el resto ve el duplicado (created=False), sin error."""
    from app.services.knowledge_rag import ingest
    from app.services.knowledge_rag.domain import DocType, SourceMetadata

    path = tmp_path / "doc.txt"
    path.write_text("contenido identico")
    meta = SourceMetadata(title="Doc", source_uri="https://example.org/doc", language="en", doc_type=DocType.ARTICLE)
    barrier = threading.Barrier(N)

    @event.listens_for(factory.kw["bind"], "after_cursor_execute")
    def _sync_after_dedupe_select(conn, cursor, statement, *_a):
        # Todos los hilos leen "no existe" antes de que ninguno inserte.
        if statement.lstrip().upper().startswith("SELECT") and "knowledge_rag_sources" in statement:
            try:
                barrier.wait(timeout=10)
            except threading.BrokenBarrierError:
                pass

    out = _race(factory, lambda s: ingest.register_source(
        s, path=path, relative_path="doc.txt", meta=meta, tenant_id=1))
    errors = [o for o in out if isinstance(o, Exception)]
    assert not errors, errors
    assert sum(1 for o in out if o.created) == 1
    assert len({o.source.id for o in out}) == 1


def test_concurrent_monthly_snapshot_freeze_first_wins(factory, monkeypatch):
    """Congelados simultáneos del mismo mes: todos devuelven la misma fila, sin error."""
    from app.services import propicks_snapshot_service as svc

    with factory() as s:
        s.add(Company(id=1, ticker="AAA", name="AAA Inc", exchange="NYSE", company_type="operating", valuation_model="dcf"))
        s.commit()
    barrier = threading.Barrier(N)

    def fake_funnel(db, top_n):
        barrier.wait(timeout=10)
        result = SimpleNamespace(company_id=1, passed=True, score=0.9, metrics={"rank": 1, "roic": 0.2})
        return [result], {"universe_size": 1, "passed_count": 1, "params": {}}

    monkeypatch.setattr(svc, "run_funnel", fake_funnel)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    out = _race(factory, lambda s: svc.freeze_monthly_snapshot(s, now=now))
    errors = [o for o in out if isinstance(o, Exception)]
    assert not errors, errors
    assert len({o.id for o in out}) == 1
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(PropickSnapshot)) == 1
