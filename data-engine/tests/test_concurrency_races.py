"""Pruebas de carreras: reintentos concurrentes idénticos deben ser idempotentes."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api.routes.paper_trading import router
from app.core.database import Base, get_db
from app.models import Tenant
from app.models.paper_trading import PaperTrade

N = 6


def _body():
    return {"proposal_key": "race-1-ASTS", "ticker": "ASTS", "direction": "long",
            "horizon": "short", "thesis": "Una tesis simulada con fuente y riesgos", "conviction": "0.8",
            "proposed_entry": "100", "stop": "90", "target": "120", "quantity": "2",
            "inference_basis": "Inferido a partir de los documentos oficiales"}


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


def test_concurrent_identical_proposal_retries_are_idempotent(factory):
    """Mismo proposal_key y mismo cuerpo en paralelo: todos 201 con el mismo id, una sola fila."""
    barrier = threading.Barrier(N)
    app = FastAPI()
    app.include_router(router)

    def override():
        with factory() as s:
            s.info["tenant_id"] = 1
            yield s

    app.dependency_overrides[get_db] = override
    client = TestClient(app)

    import app.services.paper_trading_service as svc
    real = svc.create_proposal

    def synced(db, proposal):
        existing = db.scalar(select(PaperTrade).where(PaperTrade.proposal_key == proposal.proposal_key))
        try:
            barrier.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass
        assert existing is None
        return real(db, proposal)

    import app.api.routes.paper_trading as route
    route.create_proposal = synced
    try:
        with ThreadPoolExecutor(N) as pool:
            responses = list(pool.map(lambda _: client.post("/proposals", json=_body()), range(N)))
    finally:
        route.create_proposal = real

    codes = sorted(r.status_code for r in responses)
    with factory() as s:
        rows = s.scalar(select(func.count()).select_from(PaperTrade))
    assert rows == 1
    assert codes == [201] * N, codes
    assert len({r.json()["id"] for r in responses if r.status_code == 201}) == 1
