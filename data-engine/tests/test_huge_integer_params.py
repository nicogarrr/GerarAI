"""Enteros fuera de rango en query/path no deben dar 500.

Encontrado con Schemathesis: ``offset=9223372036854775808`` (2**63) en los
listados, o un id enorme en query/body/path, llegaba hasta la base de datos y
reventaba al enlazar el parámetro (SQLite: OverflowError; Postgres: DataError
«bigint out of range»), devolviendo 500. Es entrada inválida del cliente: 422.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from app.core.database import init_db

HUGE = 2**63


@pytest.fixture()
def client():
    init_db()
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "path",
    [
        f"/api/portfolio/transactions?offset={HUGE}",
        f"/api/portfolio/transactions/page?offset={HUGE}",
        f"/api/portfolio/positions?offset={HUGE}",
        f"/api/companies?offset={HUGE}",
        f"/api/knowledge/documents?offset={HUGE}",
        f"/api/knowledge/jobs?document_id={HUGE}",
        f"/api/knowledge/principles?collection_id={HUGE}",
        f"/api/sources/documents?page={HUGE}",
    ],
)
def test_huge_integer_query_is_a_client_error(client, path):
    response = client.get(path)
    assert response.status_code == 422, (response.status_code, response.text[:300])


def test_huge_integer_path_id_is_not_a_server_error(client):
    from app.core.csrf import generate_csrf_token

    # Token CSRF valido para que el middleware deje pasar la peticion y el
    # handler responda 404/422 por el id fuera de rango (sin token seria 403).
    headers = {"X-CSRF-Token": generate_csrf_token()}
    response = client.delete(f"/api/portfolio/transactions/{HUGE}", headers=headers)
    assert response.status_code in (404, 422), (response.status_code, response.text[:300])


def test_db_out_of_range_maps_to_422_and_math_overflow_stays_500():
    from sqlalchemy.exc import DataError

    from app.core.errors import is_db_value_out_of_range

    data_error = DataError("SELECT 1", {}, Exception("bigint out of range"))
    assert is_db_value_out_of_range(data_error)

    try:
        float(10**400)
    except OverflowError as exc:
        assert not is_db_value_out_of_range(exc)
