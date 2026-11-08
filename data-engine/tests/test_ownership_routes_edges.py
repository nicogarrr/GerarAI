"""Rutas /api/ownership: sync encolada, holders 13F/N-PORT y scope 13D/G.

Sobre main (50.8% con los tests existentes) faltaban la ingesta async de
holdings del inversor (cola dedicada con contexto de tenant), el sync de
managers (uno o todos), las rutas de instituciones y fondos (404 cuando el
ticker no existe) y el scope "solo tickers seguidos" del sync SC 13D/G.
Servicios y actor sustituidos por dobles: sin SEC, sin Redis, sin LLM.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.services.fund_holders as fund_holders_mod
import app.services.insider_monitor as insider_monitor_mod
import app.services.institutional_holders as institutional_mod
import app.workers.dramatiq_app as workers
from app.api.routes import ownership as mod


def _db(tenant_id=1, user_id="user-1"):
    return SimpleNamespace(info={"tenant_id": tenant_id, "user_id": user_id})


def test_sync_managers_async_encola_con_contexto_de_tenant(monkeypatch):
    enviado = {}

    class _Actor:
        def send(self, **kwargs):
            enviado.update(kwargs)
            return SimpleNamespace(message_id="msg-1")

    monkeypatch.setattr(workers, "sync_investor_holdings", _Actor())
    out = mod.sync_managers_async(db=_db())
    assert out == {"status": "queued", "broker_message_id": "msg-1"}
    assert enviado == {"tenant_id": 1, "user_id": "user-1"}


def test_sync_managers_uno_o_todos(monkeypatch):
    service = SimpleNamespace(
        sync_manager=lambda db, cik: {"synced": cik},
        sync_all=lambda db: {"synced": "all"},
    )
    monkeypatch.setattr(mod, "ManagerHoldingIngestionService", lambda: service)
    assert mod.sync_managers(cik="0001067983", db=_db()) == {"synced": "0001067983"}
    assert mod.sync_managers(cik=None, db=_db()) == {"synced": "all"}


def test_institutional_holders_404_si_no_existe(monkeypatch):
    monkeypatch.setattr(institutional_mod, "institutional_holders", lambda db, t: None)
    with pytest.raises(HTTPException) as excinfo:
        mod.institutional_holders_route("NOPE", db=_db())
    assert excinfo.value.status_code == 404


def test_institutional_holders_camino_feliz(monkeypatch):
    monkeypatch.setattr(
        institutional_mod, "institutional_holders", lambda db, t: {"ticker": t}
    )
    assert mod.institutional_holders_route("SAN", db=_db()) == {"ticker": "SAN"}


def test_fund_holders_404_si_no_existe(monkeypatch):
    monkeypatch.setattr(fund_holders_mod, "fund_holders", lambda db, t: None)
    with pytest.raises(HTTPException) as excinfo:
        mod.fund_holders_route("NOPE", db=_db())
    assert excinfo.value.status_code == 404


def test_fund_holders_camino_feliz(monkeypatch):
    monkeypatch.setattr(fund_holders_mod, "fund_holders", lambda db, t: {"ticker": t})
    assert mod.fund_holders_route("SAN", db=_db()) == {"ticker": "SAN"}


def test_schedule_13dg_sync_rechaza_ticker_no_seguido(monkeypatch):
    # El sync gasta peticiones a la SEC: solo para tickers de la watchlist o
    # cartera del tenant; cualquier otro sale 404.
    monkeypatch.setattr(insider_monitor_mod, "watchlist_tickers", lambda db, tid: set())
    with pytest.raises(HTTPException) as excinfo:
        mod.schedule_13dg_sync(ticker="nope", db=_db())
    assert excinfo.value.status_code == 404


def test_schedule_13dg_sync_escanea_el_ticker_seguido(monkeypatch):
    monkeypatch.setattr(
        insider_monitor_mod, "watchlist_tickers", lambda db, tid: {"SAN"}
    )
    escaneo = {}
    monkeypatch.setattr(
        mod.schedule13dg_monitor,
        "scan",
        lambda db, tenant_id, tickers: escaneo.update(
            tenant_id=tenant_id, tickers=tickers
        )
        or {"status": "ok"},
    )
    assert mod.schedule_13dg_sync(ticker=" san ", db=_db()) == {"status": "ok"}
    assert escaneo == {"tenant_id": 1, "tickers": ["SAN"]}
