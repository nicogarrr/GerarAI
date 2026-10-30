"""Entradas absurdas en calendario y cotizaciones: 4xx, nunca 500."""

from fastapi.testclient import TestClient

from app.core.database import init_db
from main import app


def _client():
    init_db()
    return TestClient(app, raise_server_exceptions=False)


def test_calendario_con_desde_en_el_ultimo_dia_representable_es_400():
    client = _client()
    for path in ("/api/calendar/earnings", "/api/calendar/dividends", "/api/calendar/followed", "/api/calendar/catalysts"):
        response = client.get(path, params={"desde": "9999-12-31"})
        assert response.status_code == 400, (path, response.status_code, response.text)


def test_simbolo_con_caracteres_de_control_es_404_sin_llamar_al_proveedor(monkeypatch):
    from app.api.routes import market

    def _no_network(*_args, **_kwargs):  # pragma: no cover - fallaria el test
        raise AssertionError("no debe llamar al proveedor")

    monkeypatch.setattr(market, "_fetch_yahoo_quote", _no_network)
    monkeypatch.setattr(market, "_fetch_yahoo_candles", _no_network)
    client = _client()
    assert client.get("/api/market/quote/%00").status_code == 404
    assert client.get("/api/market/quote/A%0AB").status_code == 404
    assert client.get("/api/market/candles/%00", params={"from": 0, "to": 10}).status_code == 404
