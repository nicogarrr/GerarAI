"""Un mismo objetivo repetido dentro de una categoría («NVDA» dos veces, o
«Tecnología» y «tecnología») hacía que la desviación saliera dos veces con
sugerencias contradictorias. El formulario ya lo impide («No repitas el mismo
objetivo dentro de una categoría»); la API lo rechaza igual (422)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.plan import PlanUpsertInput, router
from app.core.database import get_db


def _payload(targets):
    return {"monthly_contribution": 300, "start_date": "2026-01-31", "target_allocations": targets}


@pytest.mark.parametrize("targets", [
    [{"kind": "ticker", "label": "NVDA", "target_pct": 30},
     {"kind": "ticker", "label": "nvda ", "target_pct": 20}],
    [{"kind": "sector", "label": "Tecnología", "target_pct": 50},
     {"kind": "sector", "label": "tecnología", "target_pct": 30}],
    [{"kind": "asset_class", "label": "Equity", "target_pct": 40},
     {"kind": "asset_class", "label": " Equity", "target_pct": 40}],
])
def test_objetivo_repetido_en_la_misma_categoria_se_rechaza(targets):
    with pytest.raises(ValidationError, match="repet"):
        PlanUpsertInput.model_validate(_payload(targets))


def test_misma_etiqueta_en_categorias_distintas_vale():
    plan = PlanUpsertInput.model_validate(_payload([
        {"kind": "ticker", "label": "GOLD", "target_pct": 10},
        {"kind": "asset_class", "label": "Gold", "target_pct": 10},
        {"kind": "sector", "label": "Gold", "target_pct": 10},
    ]))
    assert len(plan.target_allocations) == 3


def test_ruta_responde_422_sin_tocar_la_bd():
    app = FastAPI()
    app.include_router(router, prefix="/api/plan")

    def _no_db():
        # Sin base real: si la peticion llegara al handler, fallaria con 500.
        yield object()

    app.dependency_overrides[get_db] = _no_db
    resp = TestClient(app).put("/api/plan", json=_payload([
        {"kind": "ticker", "label": "MSFT", "target_pct": 40},
        {"kind": "ticker", "label": "msft", "target_pct": 40},
    ]))
    assert resp.status_code == 422, resp.text
