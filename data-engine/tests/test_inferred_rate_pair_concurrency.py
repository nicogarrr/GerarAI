"""Rates serialize within a tenant; other tenants cannot invalidate a rate pair."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes.companies import router
from app.core.database import Base, get_db
from app.models.entities import Company, InferredInput, Tenant
from app.services.inferred_input_llm_service import save_within_quota
from app.services.inferred_input_service import (
    MIN_WACC_TERMINAL_SPREAD,
    InferredInputError,
    InferredInputService,
)

BASE_TEXT = "Dado el documento publicado inferimos esta tasa anual de capital."
URLS = ["https://www.sec.gov/Archives/10k.htm"]


@pytest.mark.parametrize("same_tenant", [True, False])
@pytest.mark.parametrize("paths", [("llm", "llm"), ("manual", "manual"), ("llm", "manual"), ("manual", "llm")])
def test_concurrent_rate_pairs_are_private_and_coherent(tmp_path, monkeypatch, paths, same_tenant):
    engine = create_engine(f"sqlite:///{tmp_path / 'rates.db'}", connect_args={"timeout": 10})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Tenant(id=1, external_id="one"), Tenant(id=2, external_id="two")])
        db.add(Company(id=1, ticker="ASTS", name="AST", exchange="NASDAQ",
                       company_type="growth", valuation_model="pre_revenue"))
        db.commit()
    # Both operations have reached their short save phase, before acquiring
    # the shared company lock. This races the real HTTP manual path against
    # the LLM save path, not two calls behind a single tenant quota lock.
    ready = threading.Barrier(2)
    original = InferredInputService.create_guarded

    def synchronized_create(self, db, company_id, **kwargs):
        # Same-tenant LLM writes already serialize on the quota lock.
        if not (same_tenant and paths == ("llm", "llm")):
            ready.wait(timeout=10)
        return original(self, db, company_id, **kwargs)

    monkeypatch.setattr(InferredInputService, "create_guarded", synchronized_create)

    def write(tenant, key, value, path):
        with Session(engine) as db:
            db.info["tenant_id"] = tenant
            if path == "llm":
                try:
                    save_within_quota(db, SimpleNamespace(id=1), value, BASE_TEXT, URLS,
                                      datetime.now(UTC), key)
                    return 201
                except InferredInputError as exc:
                    assert "spread_wacc_terminal_insuficiente" in str(exc)
                    return 422
            app = FastAPI()
            app.include_router(router, prefix="/companies")
            app.dependency_overrides[get_db] = lambda: db
            with TestClient(app) as client:
                response = client.post("/companies/ASTS/inferred-inputs", json={
                    "input_key": key, "value": str(value), "base": BASE_TEXT, "source_urls": URLS,
                })
                if response.status_code == 422:
                    assert "spread_wacc_terminal_insuficiente" in response.text
                return response.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write, 1, "wacc", Decimal("0.055"), paths[0]),
                       pool.submit(write, 1 if same_tenant else 2, "terminal_growth", Decimal("0.05"), paths[1])]
            statuses = [future.result(timeout=20) for future in futures]
        assert sorted(statuses) == ([201, 422] if same_tenant else [201, 201])
        with Session(engine) as db:
            rows = db.scalars(select(InferredInput).execution_options(include_all_tenants=True)).all()
            if not same_tenant:
                assert len(rows) == 2 and {row.tenant_id for row in rows} == {1, 2}
                return
            assert len(rows) == 1
            wacc = float(rows[0].value) if rows[0].input_key == "wacc" else 0.10
            terminal = float(rows[0].value) if rows[0].input_key == "terminal_growth" else 0.03
            assert wacc - terminal >= MIN_WACC_TERMINAL_SPREAD - 1e-9
    finally:
        engine.dispose()
