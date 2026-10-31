"""Contrato limit/offset de /api/portfolio/positions (bug: truncado silencioso).

El índice de /research (lib/actions/research.actions.ts,
getResearchPortfolioPositions -> paginateAll) pide
`/api/portfolio/positions?limit=2000&offset=N`. La ruta solo declaraba
`page`/`page_size` (máx 200): FastAPI descarta los parámetros desconocidos y
devuelve siempre la primera página de 20, así que un tenant con más de 20
posiciones veía solo 20 y el índice las rotulaba como completas.

La ruta acepta ahora `limit`/`offset` como alias aditivo con precedencia
sobre `page`/`page_size`.
"""

from fastapi.testclient import TestClient

from app.core.database import init_db
from main import app

POSITIONS = 25  # > page_size por defecto (20): antes del fix solo volvían 20


def _client():
    init_db()
    client = TestClient(app)
    token = client.get("/api/csrf-token").json()["csrf_token"]
    client.headers.update({"x-csrf-token": token})
    return client


def _seed_positions(client, count):
    for i in range(count):
        response = client.post("/api/portfolio/transactions", json={
            "ticker": f"ALIAS{i:02d}", "action": "buy", "quantity": "1",
            "price": "10", "currency": "EUR", "trade_date": "2024-01-02",
        })
        assert response.status_code == 201, response.text


def test_limit_offset_devuelve_todas_las_posiciones():
    client = _client()
    _seed_positions(client, POSITIONS)
    payload = client.get("/api/portfolio/positions?limit=2000&offset=0").json()
    assert len(payload["items"]) == POSITIONS
    assert payload["page_info"]["total_items"] == POSITIONS


def test_limit_offset_pagina_con_offset():
    client = _client()
    _seed_positions(client, POSITIONS)
    payload = client.get("/api/portfolio/positions?limit=10&offset=20").json()
    assert len(payload["items"]) == POSITIONS - 20


def test_page_page_size_siguen_funcionando():
    client = _client()
    _seed_positions(client, POSITIONS)
    page1 = client.get("/api/portfolio/positions?page=1&page_size=20").json()
    page2 = client.get("/api/portfolio/positions?page=2&page_size=20").json()
    assert len(page1["items"]) == 20
    assert len(page2["items"]) == POSITIONS - 20
