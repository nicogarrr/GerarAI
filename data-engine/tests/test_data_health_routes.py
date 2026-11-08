"""Rutas de salud de datos: inventario, shorts y refresh con 404 limpio.

Los servicios se sustituyen por dobles y las funciones de la ruta se llaman
directamente: lo que se prueba es solo el mapeo de la funcion al resultado
(el ticker desconocido devuelve 404 con el error de UI en vez de un 500, y
cada endpoint devuelve el payload de su servicio). No se prueba la capa
HTTP, la auth, ni el aislamiento de hilos real del despliegue.
"""

from __future__ import annotations

import asyncio
from functools import wraps
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import data_health as data_health_routes


def run_async(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return wrapped


@pytest.fixture
def company():
    return Mock(id=7, ticker="ACME")


class TestInventory:
    def test_inventario_devuelve_el_payload(self, monkeypatch):
        monkeypatch.setattr(
            data_health_routes, "read_inventory", lambda db: {"tables": 3}
        )
        assert data_health_routes.data_health(db=object()) == {"tables": 3}


class TestShorts:
    def test_ticker_desconocido_es_404_no_500(self, monkeypatch):
        monkeypatch.setattr(
            data_health_routes, "resolve_company", lambda db, ticker: None
        )
        with pytest.raises(HTTPException) as exc:
            data_health_routes.shorts(ticker="NOPE", db=object())
        assert exc.value.status_code == 404

    def test_shorts_devuelve_el_snapshot(self, monkeypatch, company):
        monkeypatch.setattr(
            data_health_routes, "resolve_company", lambda db, ticker: company
        )
        monkeypatch.setattr(
            data_health_routes,
            "read_shorts",
            lambda db, c: {"ticker": c.ticker, "shorts": []},
        )
        assert data_health_routes.shorts(ticker="ACME", db=object()) == {
            "ticker": "ACME",
            "shorts": [],
        }

    @run_async
    async def test_refresh_devuelve_lo_del_servicio(self, monkeypatch, company):
        monkeypatch.setattr(
            data_health_routes, "resolve_company", lambda db, ticker: company
        )

        async def _fake_refresh(db, c):
            return {"ticker": c.ticker, "refreshed": True}

        monkeypatch.setattr(data_health_routes, "refresh_shorts", _fake_refresh)
        result = await data_health_routes.shorts_refresh(ticker="ACME", db=object())
        assert result == {"ticker": "ACME", "refreshed": True}

    @run_async
    async def test_refresh_con_ticker_desconocido_es_404(self, monkeypatch):
        monkeypatch.setattr(
            data_health_routes, "resolve_company", lambda db, ticker: None
        )
        with pytest.raises(HTTPException) as exc:
            await data_health_routes.shorts_refresh(ticker="NOPE", db=object())
        assert exc.value.status_code == 404
