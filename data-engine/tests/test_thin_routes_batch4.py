"""Huecos de cobertura en language, investors, cache y search (lote 4).

Cuatro rutas ya tenian tests propios pero con ramas sin cubrir (medicion
previa con los tests que referencian cada modulo): language 96 % (los dos
401 de _tenant_or_401), investors 85 % (portfolio-overlap, holders y su
404), cache 98 % (GET /stats) y search 94 % (ValueError -> 400). Estos
tests cierran esas ramas llamando a las funciones de ruta con servicios
doblados.

Que NO se prueba aqui: nada de HTTP, middleware ni auth firmada (la ruta
de idioma si tiene tests de API firmada en test_settings_language_route.py;
aqui solo se cubre la guardia de identidad llamando a la funcion con una
sesion doblada), ningun servicio real (13F, buscador universal, cache
subyacente) y ninguna logica de DCA: /invalidate/dca no se ejercita en
este archivo (queda fuera por la exclusion de DCA del encargo).
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import cache as cache_route
from app.api.routes import investors as investors_route
from app.api.routes import language as language_route
from app.api.routes import search as search_route

# --- language: guardia de identidad (los dos 401) -----------------------


def test_language_sin_tenant_id_es_401():
    """db.info sin tenant_id -> 401 identidad requerida (rama 1)."""
    db = Mock()
    db.info = {}
    with pytest.raises(HTTPException) as exc:
        language_route._tenant_or_401(db)
    assert exc.value.status_code == 401
    db.scalar.assert_not_called()


def test_language_tenant_inexistente_es_401():
    """tenant_id presente pero sin fila en Tenant -> 401 (rama 2)."""
    db = Mock()
    db.info = {"tenant_id": 123}
    db.scalar.return_value = None
    with pytest.raises(HTTPException) as exc:
        language_route._tenant_or_401(db)
    assert exc.value.status_code == 401


# --- investors: overlap, holders y cartera inexistente -------------------


def test_investors_overlap_delega_en_el_servicio(monkeypatch):
    """GET /investors/portfolio-overlap devuelve lo del servicio doblado."""
    from app.services import investor_overlap

    monkeypatch.setattr(
        investor_overlap, "portfolio_overlap", lambda db: {"pairs": []}
    )
    assert investors_route.overlap_route(db=Mock()) == {"pairs": []}


def test_investors_holders_devuelve_la_vista_inversa(monkeypatch):
    """GET /investors/holders/{ticker}: ticker con gestores -> payload."""
    from app.services import investor_overlap

    monkeypatch.setattr(
        investor_overlap,
        "holders_by_ticker",
        lambda db, ticker: {"ticker": ticker, "holders": [" Berkshire"]},
    )
    result = investors_route.holders_by_ticker_route(ticker="BRK.B", db=Mock())
    assert result["ticker"] == "BRK.B"


def test_investors_holders_ticker_desconocido_es_404(monkeypatch):
    """holders_by_ticker devuelve None (compania no encontrada) -> 404."""
    from app.services import investor_overlap

    monkeypatch.setattr(investor_overlap, "holders_by_ticker", lambda db, t: None)
    with pytest.raises(HTTPException) as exc:
        investors_route.holders_by_ticker_route(ticker="NOPE", db=Mock())
    assert exc.value.status_code == 404


def test_investors_cartera_de_inversor_desconocido_es_404(monkeypatch):
    """investor_portfolio devuelve None -> 404 sin tocar nada mas."""
    from app.services import investor_portfolio as investor_portfolio_service

    monkeypatch.setattr(
        investor_portfolio_service, "investor_portfolio", lambda db, slug: None
    )
    with pytest.raises(HTTPException) as exc:
        investors_route.investor_portfolio_route(slug="nadie", db=Mock())
    assert exc.value.status_code == 404


# --- cache: GET /stats ----------------------------------------------------


def test_cache_stats_devuelve_las_estadisticas(monkeypatch):
    """GET /cache/stats devuelve tal cual las estadisticas del core."""
    esperado = {"market_data": {"hits": 3, "misses": 1, "hit_rate": 75.0}}
    monkeypatch.setattr(cache_route, "get_cache_stats", lambda: esperado)
    assert cache_route.get_stats() == esperado


# --- search: ValueError del servicio -> 400 -------------------------------


def test_search_value_error_del_servicio_es_400(monkeypatch):
    """Un ValueError del buscador (filtros invalidos) se traduce a 400."""

    class ServicioRoto:
        def search(self, *args, **kwargs):
            raise ValueError("date_from posterior a date_to")

    monkeypatch.setattr(search_route, "UniversalSearchService", ServicioRoto)
    payload = search_route.UniversalSearchRequest(query="iberdrola")
    with pytest.raises(HTTPException) as exc:
        search_route.universal_search(payload=payload, db=Mock())
    assert exc.value.status_code == 400
    assert "date_from" in exc.value.detail
