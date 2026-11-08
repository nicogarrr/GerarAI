"""Rutas de calendario macro y 8-K: fechas por defecto, 400 limpio y auth.

Los servicios se sustituyen por dobles y las funciones de la ruta se llaman
directamente: lo que se prueba es solo el mapeo de la funcion al resultado
(fechas por defecto Madrid + 60 dias, desbordes y ValueError del servicio =
400 del cliente, paginacion por rodajas, y /8k sin tenant = 401). No se
prueba la capa HTTP ni la auth real del despliegue.
"""

from __future__ import annotations

import asyncio
from datetime import date
from functools import wraps
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api.routes import macro_calendar as macro_routes


def run_async(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return wrapped


@pytest.fixture
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(macro_routes, "local_today", lambda: date(2026, 11, 8))
    return date(2026, 11, 8)


@pytest.fixture
def service(monkeypatch):
    doble = Mock()
    doble.get_macro_events = AsyncMock(return_value={"events": [], "status": "ok"})
    monkeypatch.setattr(macro_routes, "macro_calendar_service", doble)
    return doble


class TestMacroEvents:
    @run_async
    async def test_fechas_por_defecto_hoy_mas_60_dias(self, hoy_fijo, service):
        await macro_routes.macro_events(desde=None, hasta=None, page=1, page_size=15)
        service.get_macro_events.assert_awaited_once_with(date(2026, 11, 8), date(2027, 1, 7))

    @run_async
    async def test_desborde_de_fecha_es_400_no_500(self, service):
        with pytest.raises(HTTPException) as exc:
            await macro_routes.macro_events(desde=date(9999, 12, 31), hasta=None, page=1, page_size=15)
        assert exc.value.status_code == 400

    @run_async
    async def test_value_error_del_servicio_es_400(self, service):
        service.get_macro_events.side_effect = ValueError("rango imposible")
        with pytest.raises(HTTPException) as exc:
            await macro_routes.macro_events(desde=date(2026, 1, 1), hasta=date(2026, 2, 1), page=1, page_size=15)
        assert exc.value.status_code == 400
        assert "rango imposible" in str(exc.value.detail)

    @run_async
    async def test_paginacion_corta_la_lista(self, hoy_fijo, service):
        service.get_macro_events.return_value = {
            "events": [{"id": i} for i in range(20)],
            "status": "ok",
        }
        result = await macro_routes.macro_events(page=2, page_size=5)
        assert [e["id"] for e in result["events"]] == [5, 6, 7, 8, 9]
        assert result["page"] == 2 and result["page_size"] == 5


class TestEightK:
    def _db(self, tenant_id):
        return Mock(info={"tenant_id": tenant_id})

    def test_sin_tenant_es_401(self, monkeypatch):
        digest = Mock()
        monkeypatch.setattr(macro_routes, "eight_k_digest", digest)
        with pytest.raises(HTTPException) as exc:
            macro_routes.eight_k(db=self._db(None))
        assert exc.value.status_code == 401
        digest.assert_not_called()

    def test_con_tenant_devuelve_el_digest(self, monkeypatch):
        digest = Mock(return_value={"items": []})
        monkeypatch.setattr(macro_routes, "eight_k_digest", digest)
        db = self._db(3)
        assert macro_routes.eight_k(page=2, page_size=20, db=db) == {"items": []}
        digest.assert_called_once_with(db, page=2, page_size=20)
