"""Rutas de operaciones de politicos: validaciones y 404 limpio.

El servicio se sustituye por un doble: lo que se prueba es el contrato de la
ruta (ticker vacio o larguisimo = 422, clave larguisima = 422, miembro sin
declaraciones = 404, filtros y paginacion llegan intactos al servicio).
"""

from __future__ import annotations

from unittest.mock import ANY, Mock

import pytest
from fastapi import HTTPException

from app.api.routes import politicians as politicians_routes


@pytest.fixture
def service(monkeypatch):
    doble = Mock()
    monkeypatch.setattr(politicians_routes, "politician_trades", doble)
    return doble


def test_listado_pasa_filtros_y_paginacion_al_servicio(service):
    service.politicians.return_value = {"items": []}
    result = politicians_routes.politicians_list(
        chamber="senate", party="D", sort="late", q="pelosi", limit=5, offset=10, db=object()
    )
    assert result == {"items": []}
    service.politicians.assert_called_once_with(
        ANY, chamber="senate", party="D", sort="late", query="pelosi", limit=5, offset=10
    )


class TestTicker:
    def test_ticker_vacio_es_422(self, service):
        with pytest.raises(HTTPException) as exc:
            politicians_routes.politicians_ticker(ticker="", db=object())
        assert exc.value.status_code == 422
        service.ticker_trades.assert_not_called()

    def test_ticker_larguisimo_es_422(self, service):
        with pytest.raises(HTTPException) as exc:
            politicians_routes.politicians_ticker(ticker="X" * 21, db=object())
        assert exc.value.status_code == 422
        service.ticker_trades.assert_not_called()

    def test_ticker_valido_devuelve_las_operaciones(self, service):
        service.ticker_trades.return_value = {"ticker": "ACME", "trades": []}
        assert politicians_routes.politicians_ticker(ticker="ACME", db=object())["ticker"] == "ACME"


class TestMember:
    def test_clave_larguisima_es_422(self, service):
        with pytest.raises(HTTPException) as exc:
            politicians_routes.politicians_member(member_key="k" * 121, db=object())
        assert exc.value.status_code == 422
        service.member_detail.assert_not_called()

    def test_miembro_sin_declaraciones_es_404(self, service):
        service.member_detail.return_value = None
        with pytest.raises(HTTPException) as exc:
            politicians_routes.politicians_member(member_key="desconocido", db=object())
        assert exc.value.status_code == 404

    def test_miembro_con_ficha_devuelve_el_detalle(self, service):
        service.member_detail.return_value = {"member": "Perez", "trades": []}
        assert politicians_routes.politicians_member(member_key="perez", db=object())["member"] == "Perez"
