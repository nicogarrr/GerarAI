"""La API rechaza objetivos que suman mas del 100 % dentro de una dimension."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routes.plan import PlanUpsertInput


def _payload(targets):
    return {"monthly_contribution": 300, "start_date": "2026-01-31", "target_allocations": targets}


def test_tickers_over_100_are_rejected():
    with pytest.raises(ValidationError, match="ticker suman 120"):
        PlanUpsertInput.model_validate(_payload([
            {"kind": "ticker", "label": "MSFT", "target_pct": 60},
            {"kind": "ticker", "label": "NVDA", "target_pct": 60},
        ]))


def test_each_dimension_may_reach_100_on_its_own():
    plan = PlanUpsertInput.model_validate(_payload([
        {"kind": "ticker", "label": "MSFT", "target_pct": 70},
        {"kind": "ticker", "label": "NVDA", "target_pct": 30},
        {"kind": "sector", "label": "Technology", "target_pct": 100},
        {"kind": "asset_class", "label": "Equity", "target_pct": 99.99},
    ]))
    assert len(plan.target_allocations) == 4


def test_floating_point_sum_of_thirds_is_not_overallocated():
    PlanUpsertInput.model_validate(_payload([
        {"kind": "sector", "label": s, "target_pct": 33.333333333}
        for s in ("A", "B", "C")
    ]))


def test_route_answers_422_before_touching_the_db():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes.plan import router
    from app.core.database import get_db

    app = FastAPI()
    app.include_router(router, prefix="/api/plan")

    def _no_db():
        # Sin base real: si la peticion llegara al handler, fallaria con 500.
        yield object()

    app.dependency_overrides[get_db] = _no_db
    response = TestClient(app).put("/api/plan", json=_payload([
        {"kind": "sector", "label": "Technology", "target_pct": 80},
        {"kind": "sector", "label": "Health", "target_pct": 30},
    ]))
    assert response.status_code == 422
    assert "sector suman 110" in response.text
