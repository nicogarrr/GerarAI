"""Watchlist y alertas: entradas imposibles por API.

Fuzzing de los endpoints de watchlist y alertas (la web no produce estos
valores; una llamada directa sí):

- ``POST /api/watchlist`` aceptaba «.», «-» o «A..B» como ticker: se creaba la
  fila y se encolaban el análisis y la siembra de la SEC para un símbolo que no
  existe.
- La etiqueta ``company`` aceptaba caracteres de control; un NUL («\x00») hace
  fallar el INSERT en Postgres (500).
- Un umbral de alerta «1e400» es un Decimal finito pero no cabe en un float:
  pasaba la validación y «avisar si baja de 1e400» se cumplía siempre.
- ``POST /api/alerts/{id}/action`` aceptaba un ``actor`` de cualquier longitud
  para ``acknowledged_by`` (String(160)): en Postgres, 500.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
from app.api.routes.alerts import ManualAlertCreate
from app.core import auth as auth_module
from app.core.database import init_db
from app.schemas.api import ResearchAlertAction
from app.services.alert_rule_service import _numeric_threshold
from tests.auth_helpers import auth_settings, signed_request

SECRET = "watchlist-bounds-secret"


@pytest.fixture()
def call(monkeypatch):
    init_db()
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET, app_env="test")
    )
    suffix = uuid4().hex[:8]
    client = TestClient(main.app, raise_server_exceptions=False)

    def _call(method, path, json_body=None):
        return signed_request(client, SECRET, f"wb-{suffix}", f"user-wb-{suffix}", method, path, json_body=json_body)

    return _call


@pytest.mark.parametrize("symbol", [".", "-", "..", "A..B", "-AAPL", "AAPL.", "A.-B"])
def test_watchlist_rechaza_tickers_sin_forma(call, symbol):
    response = call("POST", "/api/watchlist", {"symbol": symbol})
    assert response.status_code == 422, response.text
    assert all(item["symbol"] != symbol for item in call("GET", "/api/watchlist").json())


@pytest.mark.parametrize("symbol", ["AAPL", "brk.b", "BF-B", "0700.HK", "7203.T", "RDS-A"])
def test_watchlist_sigue_aceptando_tickers_reales(call, symbol, monkeypatch):
    monkeypatch.setattr("app.api.routes.watchlist.enqueue_tracked_analysis", lambda *a, **k: None)
    monkeypatch.setattr("app.api.routes.watchlist.enqueue_fundamentals_seed", lambda *a, **k: None)
    response = call("POST", "/api/watchlist", {"symbol": symbol, "company": "Empresa S.A."})
    assert response.status_code == 201, response.text
    assert response.json()["symbol"] == symbol.upper()


@pytest.mark.parametrize("company", ["Apple\x00", "Apple\nAprobar", "Apple\r", "\u2028Apple"])
def test_watchlist_rechaza_etiqueta_con_caracteres_de_control(call, company, monkeypatch):
    monkeypatch.setattr("app.api.routes.watchlist.enqueue_tracked_analysis", lambda *a, **k: None)
    monkeypatch.setattr("app.api.routes.watchlist.enqueue_fundamentals_seed", lambda *a, **k: None)
    response = call("POST", "/api/watchlist", {"symbol": "AAPL", "company": company})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("value", ["1e400", "-1e400", 10**400])
def test_umbral_que_no_cabe_en_float_no_es_un_numero(value):
    assert _numeric_threshold(value) is None
    with pytest.raises(ValidationError):
        ManualAlertCreate(ticker="AAPL", alert_type="price_below", operator="<", value=value)


def test_umbrales_normales_siguen_valiendo():
    assert _numeric_threshold("1e300") == 1e300
    assert ManualAlertCreate(ticker="AAPL", alert_type="price_below", operator="<", value="12.5").value == "12.5"


def test_actor_de_la_accion_cabe_en_su_columna():
    with pytest.raises(ValidationError):
        ResearchAlertAction(action="acknowledge", actor="x" * 161)
    assert ResearchAlertAction(action="acknowledge", actor="x" * 160).actor == "x" * 160
    assert ResearchAlertAction(action="acknowledge").actor == "user"
