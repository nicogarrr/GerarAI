"""realqa-20: una cuenta nueva veia «Aún no hay 13F sincronizados» hasta el
lunes siguiente. Las carteras 13F se guardan por cuenta y el cron es semanal
(lunes 04:20 UTC); en produccion las 8 cuentas antiguas tenian 2218 posiciones
cada una y la cuenta creada hoy, 0. La ficha encola ahora la primera descarga.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.routes import insider as insider_routes
from app.services import ticker_ownership_signals as signals


def test_holders_signal_sin_13f_en_la_cuenta_da_motivo_y_cadencia(monkeypatch):
    monkeypatch.setattr(signals, "holders_by_ticker", lambda db, t: {"status": "sin_datos", "cusip": "037833100"})
    result = signals.holders_signal(SimpleNamespace(), "AAPL")
    assert result["status"] == "sin_datos"
    assert result["reason"] == "sin_sincronizar"
    assert "cada lunes" in result["detail"]


def test_sin_identificador_no_marca_sin_sincronizar(monkeypatch):
    monkeypatch.setattr(signals, "holders_by_ticker", lambda db, t: {"status": "sin_identificador", "cusip": None})
    assert "reason" not in signals.holders_signal(SimpleNamespace(), "CGEO.L")


class _Sent:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message_id="m1")


@pytest.fixture
def fake_actor(monkeypatch):
    from app.workers import dramatiq_app

    sent = _Sent()
    monkeypatch.setattr(dramatiq_app, "sync_investor_holdings", sent)
    insider_routes._first_13f_sync_at.clear()
    yield sent
    insider_routes._first_13f_sync_at.clear()


def _signals_without_13f(db, ticker):
    return {
        "ticker": ticker,
        "insider": {"status": "ok"},
        "holders": {"status": "sin_datos", "reason": "sin_sincronizar", "detail": "x"},
    }


def test_la_ficha_encola_una_vez_la_primera_descarga_13f(monkeypatch, fake_actor):
    monkeypatch.setattr(insider_routes, "ownership_signals", _signals_without_13f)
    db = SimpleNamespace(info={"tenant_id": 13, "user_id": "u13"})
    out = insider_routes.insider_ownership_signals(ticker="AAPL", db=db)
    assert out["holders"]["sync"] == "queued"
    assert "primera descarga" in out["holders"]["detail"]
    assert fake_actor.calls == [{"tenant_id": 13, "user_id": "u13"}]
    # Recargar la ficha no vuelve a encolar dentro del enfriamiento.
    again = insider_routes.insider_ownership_signals(ticker="AAPL", db=db)
    assert again["holders"]["sync"] == "queued"
    assert len(fake_actor.calls) == 1
    # Otra cuenta sí encola la suya.
    insider_routes.insider_ownership_signals(ticker="AAPL", db=SimpleNamespace(info={"tenant_id": 14, "user_id": "u14"}))
    assert [c["tenant_id"] for c in fake_actor.calls] == [13, 14]


def test_con_13f_no_encola_nada(monkeypatch, fake_actor):
    monkeypatch.setattr(
        insider_routes,
        "ownership_signals",
        lambda db, t: {"ticker": t, "holders": {"status": "ok", "holders": 3}},
    )
    out = insider_routes.insider_ownership_signals(ticker="AAPL", db=SimpleNamespace(info={"tenant_id": 2}))
    assert "sync" not in out["holders"]
    assert fake_actor.calls == []


def test_sin_broker_la_ficha_sigue_respondiendo(monkeypatch):
    from app.workers import dramatiq_app

    class _Broken:
        def send(self, **kwargs):
            raise ConnectionError("redis caído")

    monkeypatch.setattr(dramatiq_app, "sync_investor_holdings", _Broken())
    monkeypatch.setattr(insider_routes, "ownership_signals", _signals_without_13f)
    insider_routes._first_13f_sync_at.clear()
    out = insider_routes.insider_ownership_signals(ticker="AAPL", db=SimpleNamespace(info={"tenant_id": 15}))
    assert out["holders"]["status"] == "sin_datos"
    assert "sync" not in out["holders"]
