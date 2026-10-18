"""Lista 13.6: POST /portfolio/refresh-market no congela el event loop.

MarketRefreshService intercala awaits de red con trabajo SQLAlchemy sync
pesado (precios de todo el universo del tenant + revalorizacion). Como
corutina servida en el loop, esos tramos sync bloqueaban a todos los demas
requests. El handler es sync ahora: FastAPI lo sirve en su threadpool y el
puente compartido da a la corrutina su propio loop.
"""

from __future__ import annotations

import inspect

import pytest

from app.api.routes import portfolio as portfolio_routes


def test_refresh_market_handler_is_not_a_coroutine():
    assert not inspect.iscoroutinefunction(portfolio_routes.refresh_portfolio_market_data), (
        "un handler async con trabajo sync pesado congela el event loop"
    )


def test_refresh_market_returns_service_payload(monkeypatch):
    class _FakeService:
        async def refresh(self, db, *, as_of=None, companies=None):
            return {"status": "ok", "as_of": str(as_of)}

    monkeypatch.setattr(portfolio_routes, "MarketRefreshService", _FakeService)
    result = portfolio_routes.refresh_portfolio_market_data(as_of=None, db=object())
    assert result == {"status": "ok", "as_of": "None"}


def test_refresh_market_maps_value_error_to_400(monkeypatch):
    from fastapi import HTTPException

    class _FailingService:
        async def refresh(self, db, *, as_of=None, companies=None):
            raise ValueError("Tenant context is required for market refresh")

    monkeypatch.setattr(portfolio_routes, "MarketRefreshService", _FailingService)
    with pytest.raises(HTTPException) as excinfo:
        portfolio_routes.refresh_portfolio_market_data(as_of=None, db=object())
    assert excinfo.value.status_code == 400
