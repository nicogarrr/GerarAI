"""El precalentado deja construidas las rutas: la primera peticion no las paga.

FastAPI construye el contexto de cada ruta incluida la primera vez que una
peticion recorre su router; en GerarAI eso costaba cientos de ms en las
primeras peticiones tras cada arranque. ``warm_route_contexts`` lo adelanta.
"""

from __future__ import annotations

import fastapi.routing as fastapi_routing
from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.testclient import TestClient

from app.core.route_warmup import warm_route_contexts


def _dep(limit: int = Query(10)) -> int:
    return limit


def _app() -> FastAPI:
    app = FastAPI()
    outer = APIRouter()
    for n in range(5):
        inner = APIRouter()

        @inner.get(f"/items{n}/{{item_id}}")
        def _item(item_id: int, limit: int = Depends(_dep)) -> dict:
            return {"item_id": item_id, "limit": limit}

        outer.include_router(inner, prefix=f"/g{n}")
    app.include_router(outer, prefix="/api")
    return app


def _contar_construcciones(monkeypatch) -> dict[str, int]:
    contador = {"n": 0}
    builder = getattr(fastapi_routing, "_EffectiveRouteContext", None)
    if builder is None or not hasattr(builder, "from_api_route"):
        return contador
    original = builder.from_api_route.__func__

    def _contado(cls, *args, **kwargs):
        contador["n"] += 1
        return original(cls, *args, **kwargs)

    monkeypatch.setattr(builder, "from_api_route", classmethod(_contado))
    return contador


def test_precalentado_construye_las_rutas_antes_de_la_primera_peticion(monkeypatch):
    app = _app()
    contador = _contar_construcciones(monkeypatch)
    assert warm_route_contexts(app) >= 1
    construidas = contador["n"]
    respuesta = TestClient(app).get("/api/g4/items4/7?limit=3")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"item_id": 7, "limit": 3}
    # La peticion ya no construye ninguna ruta: todo quedo hecho al precalentar.
    assert contador["n"] == construidas


def test_precalentado_es_inocuo_sin_routers_incluidos():
    app = FastAPI()

    @app.get("/x")
    def _x() -> dict:
        return {"ok": True}

    assert warm_route_contexts(app) == 0
    assert TestClient(app).get("/x").json() == {"ok": True}
