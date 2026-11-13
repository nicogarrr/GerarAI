"""/api/screeners/real: `limit` acotado a 1..200 en la propia ruta (y en OpenAPI)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from app.core.database import init_db


@pytest.fixture()
def client():
    init_db()
    return TestClient(main.app, raise_server_exceptions=False)


def test_openapi_declares_limit_bounds():
    params = main.app.openapi()["paths"]["/api/screeners/real"]["get"]["parameters"]
    limit = next(p for p in params if p["name"] == "limit")["schema"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 200, 25)


@pytest.mark.parametrize("value", ["0", "-1", "201", "9999"])
def test_limit_out_of_bounds_is_a_422(client, value):
    response = client.get("/api/screeners/real", params={"limit": value})
    assert response.status_code == 422, (response.status_code, response.text[:200])
