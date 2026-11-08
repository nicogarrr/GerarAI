"""Huecos de cobertura en insider (lote 10).

Medicion previa (mismo metodo, tests que referencian el modulo): insider
86,2 %. Se cubren solo endpoints de LECTURA de datos SEC ya persistidos
(Form 4/13F), siguiendo la instruccion: /signals (feliz y con el enganche
de notificacion), y las degradaciones best-effort de /feed, /filings y
/operations (cualquier fallo -> status unavailable, nunca 500). El resumen
que alimenta la tesis NO se toca aqui.

Que NO se prueba aqui: nada de HTTP ni auth; ningun servicio real
(insider_service, insider_feed, insider_operations van doblados); la SEC
ni Telegram reales (maybe_notify_insider_buy va doblado, solo se certifica
el enganche); y las degradaciones se fuerzan con dobles que lanzan, no con
fallos reales de base de datos.
"""

from __future__ import annotations

from unittest.mock import Mock

from app.api.routes import insider as insider_route


def _db():
    db = Mock()
    db.info = {"tenant_id": 1}
    return db


def test_signals_pasa_ticker_cik_y_tenant(monkeypatch):
    """GET /insider/signals: el servicio recibe ticker, cik, limite y tenant."""
    visto = {}

    def servicio(ticker, cik, limit, db, tenant_id):
        visto.update(ticker=ticker, cik=cik, limit=limit, tenant_id=tenant_id)
        return {"ticker": ticker, "signals": []}

    monkeypatch.setattr(insider_route.insider_service, "get_signals_for_ticker", servicio)
    result = insider_route.insider_signals(
        ticker="ASTS", cik="0001", limit=5, notify=False, db=_db()
    )
    assert visto == {"ticker": "ASTS", "cik": "0001", "limit": 5, "tenant_id": 1}
    assert "notification" not in result


def test_signals_con_notify_engancha_la_notificacion(monkeypatch):
    """notify=true: se llama al enganche y su resultado va en 'notification'."""
    monkeypatch.setattr(
        insider_route.insider_service,
        "get_signals_for_ticker",
        lambda ticker, cik, limit, db, tenant_id: {"ticker": ticker, "signals": [{}]},
    )
    monkeypatch.setattr(
        insider_route.insider_service,
        "maybe_notify_insider_buy",
        lambda ticker, signals: {"sent": True, "ticker": ticker},
    )
    result = insider_route.insider_signals(
        ticker="ASTS", cik=None, limit=5, notify=True, db=_db()
    )
    assert result["notification"] == {"sent": True, "ticker": "ASTS"}


def test_feed_roto_degrada_a_unavailable(monkeypatch):
    def roto(db, days, side, ticker, limit):
        raise ConnectionError("bd caida")

    monkeypatch.setattr(insider_route.insider_feed, "build_feed", roto)
    result = insider_route.insider_feed_route(
        days=30, side="buy", ticker="ASTS", limit=10, db=_db()
    )
    assert result["status"] == "unavailable"
    assert result["reason"] == "ConnectionError"
    assert result["transactions"] == []


def test_filings_roto_degrada_a_unavailable():
    db = _db()
    db.scalars.side_effect = RuntimeError("bd caida")
    result = insider_route.insider_filings(ticker="asts", limit=5, db=db, offset=0)
    assert result["status"] == "unavailable"
    assert result["reason"] == "RuntimeError"
    assert result["ticker"] == "ASTS"
    assert result["filings"] == []


def test_operations_devuelve_el_agregado(monkeypatch):
    monkeypatch.setattr(
        insider_route.insider_operations,
        "insider_operations",
        lambda db, days: {"status": "ok", "days": days, "companies": []},
    )
    result = insider_route.insider_operations_route(days=90, db=_db())
    assert result["status"] == "ok"
    assert result["days"] == 90


def test_operations_roto_degrada_a_unavailable(monkeypatch):
    def roto(db, days):
        raise TimeoutError("bd lenta")

    monkeypatch.setattr(insider_route.insider_operations, "insider_operations", roto)
    result = insider_route.insider_operations_route(days=90, db=_db())
    assert result["status"] == "unavailable"
    assert result["reason"] == "TimeoutError"
