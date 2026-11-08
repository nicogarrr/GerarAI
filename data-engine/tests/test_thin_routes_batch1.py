"""Rutas finas de solo lectura: paso al servicio, 404/401/422 limpios.

Lote: portfolio_moves, market_context, analyst_report, filing_intelligence
y risk. Los servicios se sustituyen por dobles y las funciones de la ruta se
llaman directamente: se prueba solo el mapeo funcion -> resultado (cada
endpoint devuelve lo de su servicio; compania desconocida = 404; sin tenant
= 401; ticker invalido = 422 sin llegar al servicio). No se prueba la capa
HTTP, la auth real ni el aislamiento de hilos del despliegue.
"""

from __future__ import annotations

import asyncio
from functools import wraps
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import analyst_report as analyst_report_routes
from app.api.routes import filing_intelligence as filing_routes
from app.api.routes import market_context as market_context_routes
from app.api.routes import portfolio_moves as portfolio_moves_routes
from app.api.routes import risk as risk_routes


def run_async(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return wrapped


class TestPassthroughs:
    def test_portfolio_moves_devuelve_el_digest(self, monkeypatch):
        monkeypatch.setattr(
            portfolio_moves_routes, "latest_digest", lambda db: {"moves": 2}
        )
        assert portfolio_moves_routes.moves(db=object()) == {"moves": 2}

    def test_market_context_devuelve_el_snapshot(self, monkeypatch):
        monkeypatch.setattr(
            market_context_routes, "latest_snapshot", lambda db: {"regime": "risk-on"}
        )
        assert market_context_routes.regime(db=object()) == {"regime": "risk-on"}

    def test_risk_dashboard_devuelve_lo_del_servicio(self, monkeypatch):
        servicio = Mock()
        servicio.dashboard.return_value = {"var": 0.05}
        monkeypatch.setattr(risk_routes, "RiskService", lambda: servicio)
        assert risk_routes.risk_dashboard(db=object()) == {"var": 0.05}


class TestAnalystReport:
    def test_compania_desconocida_es_404(self, monkeypatch):
        monkeypatch.setattr(
            analyst_report_routes, "resolve_company", lambda db, ticker: None
        )
        with pytest.raises(HTTPException) as exc:
            analyst_report_routes.analyst_report(ticker="NOPE", db=object())
        assert exc.value.status_code == 404

    def test_compania_conocida_devuelve_el_informe(self, monkeypatch):
        company = Mock(id=1, ticker="ACME")
        monkeypatch.setattr(
            analyst_report_routes, "resolve_company", lambda db, ticker: company
        )
        monkeypatch.setattr(
            analyst_report_routes,
            "build_company_report",
            lambda db, c: {"ticker": c.ticker},
        )
        assert analyst_report_routes.analyst_report(ticker="ACME", db=object()) == {"ticker": "ACME"}


class TestFilingYoy:
    def _db(self, tenant_id=1):
        return Mock(info={"tenant_id": tenant_id})

    def test_compania_desconocida_es_404(self, monkeypatch):
        monkeypatch.setattr(filing_routes, "resolve_company", lambda db, ticker: None)
        with pytest.raises(HTTPException) as exc:
            filing_routes.filing_yoy(ticker="NOPE", db=self._db())
        assert exc.value.status_code == 404

    def test_sin_tenant_es_401(self, monkeypatch):
        monkeypatch.setattr(
            filing_routes, "resolve_company", lambda db, ticker: Mock(id=1)
        )
        comparar = Mock()
        monkeypatch.setattr(filing_routes, "comparison", comparar)
        with pytest.raises(HTTPException) as exc:
            filing_routes.filing_yoy(ticker="ACME", db=self._db(None))
        assert exc.value.status_code == 401
        comparar.assert_not_called()

    def test_con_tenant_devuelve_la_comparacion(self, monkeypatch):
        monkeypatch.setattr(
            filing_routes, "resolve_company", lambda db, ticker: Mock(id=9)
        )
        comparar = Mock(return_value={"forms": []})
        monkeypatch.setattr(filing_routes, "comparison", comparar)
        db = self._db(1)
        assert filing_routes.filing_yoy(ticker="ACME", form="10-Q", page=3, db=db) == {"forms": []}
        comparar.assert_called_once_with(db, 9, "10-Q", 3)


class TestHistoricalStress:
    @run_async
    async def test_ticker_invalido_es_422_sin_tocar_el_servicio(self, monkeypatch):
        with pytest.raises(HTTPException) as exc:
            await risk_routes.historical_stress(ticker="no es un ticker", db=object())
        assert exc.value.status_code == 422

    @run_async
    async def test_ticker_valido_llega_normalizado(self, monkeypatch):
        class _Servicio:
            async def build(self, db, ticker=None):
                return {"ticker": ticker}

        monkeypatch.setattr(
            "app.services.historical_stress_service.HistoricalStressService", _Servicio
        )
        result = await risk_routes.historical_stress(ticker=" acme ", db=object())
        assert result == {"ticker": "ACME"}

    @run_async
    async def test_sin_ticker_delega_en_el_servicio(self, monkeypatch):
        class _Servicio:
            async def build(self, db, ticker=None):
                return {"ticker": ticker, "scenarios": []}

        monkeypatch.setattr(
            "app.services.historical_stress_service.HistoricalStressService", _Servicio
        )
        result = await risk_routes.historical_stress(ticker=None, db=object())
        assert result == {"ticker": None, "scenarios": []}
