from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import init_db
from tests.auth_helpers import auth_settings, signed_request

SECRET = "positions-limit-offset-secret-32-chars!!"


def _client(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    suffix = uuid4().hex[:8]
    return TestClient(main.app, raise_server_exceptions=False), f"plo-{suffix}", f"user-{suffix}"


def _get(client, tenant, user, params):
    return signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/positions", params=params)


def _seed_positions(client, tenant, user, count):
    for i in range(count):
        response = signed_request(
            client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
            json_body={
                "ticker": f"ALIAS{i:02d}", "action": "buy", "quantity": "1",
                "price": "10", "currency": "EUR", "trade_date": "2024-01-02",
            },
        )
        assert response.status_code == 201, response.text


POSITIONS = 25  # > page_size por defecto (20): antes del fix solo volvían 20


def test_limit_offset_devuelve_todas_las_posiciones(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    _seed_positions(client, tenant, user, POSITIONS)
    payload = _get(client, tenant, user, {"limit": 2000, "offset": 0}).json()
    assert len(payload["items"]) == POSITIONS
    assert payload["page_info"]["total_items"] == POSITIONS


def test_limit_offset_pagina_con_offset(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    _seed_positions(client, tenant, user, POSITIONS)
    payload = _get(client, tenant, user, {"limit": 10, "offset": 20}).json()
    assert len(payload["items"]) == POSITIONS - 20


def test_offset_no_multiplo_de_limit_dice_la_verdad_en_page_info(monkeypatch):
    # Auditoria del piloto: total 25, limit 10, offset 19 -> 6 items y la
    # ventana toca el final: has_next debe ser False aunque la pagina
    # derivada por division entera (19 // 10 + 1 = 2 de 3) dijera True.
    client, tenant, user = _client(monkeypatch)
    _seed_positions(client, tenant, user, POSITIONS)
    payload = _get(client, tenant, user, {"limit": 10, "offset": 19}).json()
    assert len(payload["items"]) == POSITIONS - 19
    assert payload["page_info"]["has_next"] is False
    assert payload["page_info"]["has_prev"] is True
    assert payload["page_info"]["total_items"] == POSITIONS
    assert payload["page_info"]["total_pages"] == 3
    inicio = _get(client, tenant, user, {"limit": 10, "offset": 0}).json()
    assert inicio["page_info"]["has_next"] is True
    assert inicio["page_info"]["has_prev"] is False


def test_offset_sin_limit_es_422_explicito(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    _seed_positions(client, tenant, user, 2)
    response = _get(client, tenant, user, {"offset": 5})
    assert response.status_code == 422


def test_offset_enorme_con_limit_es_422_no_500(monkeypatch):
    # 2**63 desborda el bind de SQLite/Postgres; el guarda global de
    # app.core.errors lo traduce a 422 (entrada invalida), nunca 500.
    client, tenant, user = _client(monkeypatch)
    _seed_positions(client, tenant, user, 2)
    response = _get(client, tenant, user, {"limit": 10, "offset": "9223372036854775808"})
    assert response.status_code == 422


def test_page_page_size_siguen_funcionando(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    _seed_positions(client, tenant, user, POSITIONS)
    page1 = _get(client, tenant, user, {"page": 1, "page_size": 20}).json()
    page2 = _get(client, tenant, user, {"page": 2, "page_size": 20}).json()
    assert len(page1["items"]) == 20
    assert len(page2["items"]) == POSITIONS - 20
