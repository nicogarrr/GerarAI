"""Cableado al registry de salud de FRED, GDELT, calendario macro y ECB history.

Fulfills: VAL-DATA-004 (extensión al resto de conectores gratuitos)
Expected Behavior:
- FRED: 500/red/no-JSON degradan; 400/404 (serie inexistente) NO degradan; éxito cierra
- GDELT: 429 (por IP) y 5xx degradan; 400 (query inválida) NO degrada; éxito cierra
- FOMC/BLS (URLs fijas): cualquier error HTTP o "200 sin iCalendar" degrada
- ecb_history comparte la clave "ecb" del proveedor: fallo y éxito se agregan
"""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest

from app.services.connectors import ecb_history, fred, gdelt, macro_calendar
from app.services.data_source_health import DataSourceHealthRegistry, get_data_source_registry


@pytest.fixture(autouse=True)
def fresh_registry():
    DataSourceHealthRegistry._instance = None
    gdelt.GDELTClient._blocked_until = 0.0  # el bloqueo 429 es a nivel de clase
    yield
    DataSourceHealthRegistry._instance = None
    gdelt.GDELTClient._blocked_until = 0.0


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _json_response(status: int, body: str = "{}") -> httpx.Response:
    return httpx.Response(status, text=body, headers={"content-type": "application/json"})


# ---------- FRED ----------


def test_registry_incluye_fuentes_macro():
    registry = get_data_source_registry()
    for key in ("fred", "gdelt", "fomc_calendar", "bls_calendar", "ecb"):
        assert key in registry.sources, key


def test_fred_500_degrada(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")

    def handler(request):
        return _json_response(500, "{}")

    registry = get_data_source_registry()
    before = registry.get_status("fred").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fred.fetch_observations("cpi", client=_client(handler)))
    assert registry.get_status("fred").consecutive_failures == before + 1


def test_fred_400_serie_inexistente_no_degrada(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")

    def handler(request):
        return _json_response(400, '{"error_message":"Bad series"}')

    registry = get_data_source_registry()
    before = registry.get_status("fred").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fred.fetch_observations("SERIE_INEXISTENTE", client=_client(handler)))
    assert registry.get_status("fred").consecutive_failures == before


def test_fred_exito_cierra(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")

    def handler(request):
        return _json_response(200, '{"observations":[{"date":"2026-10-30","value":"3.2"}]}')

    registry = get_data_source_registry()
    registry.record_failure("fred", "fallo previo")
    data = asyncio.run(fred.fetch_observations("cpi", client=_client(handler)))
    assert data["observations"][0]["value"] == "3.2"
    status = registry.get_status("fred")
    assert status.consecutive_failures == 0
    assert status.last_checked_at is not None


# ---------- GDELT ----------


def test_gdelt_429_degrada():
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "9999"})

    registry = get_data_source_registry()
    before = registry.get_status("gdelt").consecutive_failures
    client = gdelt.GDELTClient(client=_client(handler), min_interval=0)
    with pytest.raises(gdelt.GdeltRateLimited):
        asyncio.run(client.news_search("iberdrola"))
    assert registry.get_status("gdelt").consecutive_failures == before + 1


def test_gdelt_400_query_invalida_no_degrada():
    def handler(request):
        return _json_response(400, "{}")

    registry = get_data_source_registry()
    before = registry.get_status("gdelt").consecutive_failures
    client = gdelt.GDELTClient(client=_client(handler), min_interval=0)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.news_search("query rota"))
    assert registry.get_status("gdelt").consecutive_failures == before


def test_gdelt_exito_cierra():
    def handler(request):
        return _json_response(200, '{"articles":[]}')

    registry = get_data_source_registry()
    registry.record_failure("gdelt", "fallo previo")
    client = gdelt.GDELTClient(client=_client(handler), min_interval=0)
    result = asyncio.run(client.news_search("iberdrola"))
    assert result == {"articles": []}
    assert registry.get_status("gdelt").consecutive_failures == 0


# ---------- Calendario macro (URLs fijas: todo error es de fuente) ----------


def test_bls_200_sin_ics_degrada():
    def handler(request):
        return httpx.Response(200, text="<html>Access Denied</html>")

    registry = get_data_source_registry()
    before = registry.get_status("bls_calendar").consecutive_failures
    with pytest.raises(ValueError, match="iCalendar"):
        asyncio.run(macro_calendar.fetch_bls("GerarAI test (contact@example.com)", client=_client(handler)))
    assert registry.get_status("bls_calendar").consecutive_failures == before + 1


def test_fomc_error_de_red_degrada():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    registry = get_data_source_registry()
    before = registry.get_status("fomc_calendar").consecutive_failures
    with pytest.raises(httpx.ConnectError):
        asyncio.run(macro_calendar.fetch_fomc("GerarAI test (contact@example.com)", client=_client(handler)))
    assert registry.get_status("fomc_calendar").consecutive_failures == before + 1


def test_fomc_exito_cierra():
    html = (
        '<div class="panel-heading"><h4><a id="1">2026 FOMC Meetings</a></h4></div>'
        '<div class="row fomc-meeting"><div class="fomc-meeting__month col"><strong>January</strong></div>'
        '<div class="fomc-meeting__date col">27-28</div></div>'
    )

    def handler(request):
        return httpx.Response(200, text=html)

    registry = get_data_source_registry()
    registry.record_failure("fomc_calendar", "fallo previo")
    events = asyncio.run(
        macro_calendar.fetch_fomc("GerarAI test (contact@example.com)", client=_client(handler))
    )
    assert events
    assert registry.get_status("fomc_calendar").consecutive_failures == 0


# ---------- ECB history (comparte clave "ecb") ----------


def test_ecb_history_fallo_agrega_en_ecb(monkeypatch):
    def handler(request):
        return httpx.Response(500, text="")

    real_async_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(ecb_history.httpx, "AsyncClient", fake_client)
    registry = get_data_source_registry()
    before = registry.get_status("ecb").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(ecb_history.fetch_ecb_csv(["USD"], start=date(2026, 1, 1), end=date(2026, 1, 2)))
    assert registry.get_status("ecb").consecutive_failures == before + 1


def test_ecb_history_exito_agrega_en_ecb(monkeypatch):
    def handler(request):
        return httpx.Response(200, text="TIME_PERIOD,USD\n2026-01-01,1.08\n")

    real_async_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(ecb_history.httpx, "AsyncClient", fake_client)
    registry = get_data_source_registry()
    registry.record_failure("ecb", "fallo previo")
    text = asyncio.run(ecb_history.fetch_ecb_csv(["USD"], start=date(2026, 1, 1), end=date(2026, 1, 2)))
    assert "TIME_PERIOD" in text
    assert registry.get_status("ecb").consecutive_failures == 0


# ---------- Bloqueos del piloto (#3433) ----------


def test_fred_series_429_agotado_degrada(monkeypatch):
    """UpstreamRateLimited (get_with_retry) no es HTTPStatusError: sin captura
    propia, un 429 agotado salia sin registrar fallo."""
    from app.services.connectors.base import UpstreamRateLimited

    monkeypatch.setenv("FRED_API_KEY", "test-key")

    def handler(request):
        return _json_response(429, "{}")

    registry = get_data_source_registry()
    before = registry.get_status("fred").consecutive_failures
    client = fred.FREDClient(client=_client(handler))
    with pytest.raises(UpstreamRateLimited):
        asyncio.run(client.series("CPIAUCSL"))
    assert registry.get_status("fred").consecutive_failures == before + 1


def test_fred_series_csv_200_html_no_es_exito(monkeypatch):
    """Un 200 con HTML challenge debe registrar FALLO, no salud."""

    def handler(request):
        return httpx.Response(200, text="<html><body>challenge</body></html>")

    registry = get_data_source_registry()
    before = registry.get_status("fred").consecutive_failures
    client = fred.FREDClient(client=_client(handler))
    with pytest.raises(RuntimeError, match="CSV"):
        asyncio.run(client.series_csv("CPIAUCSL"))
    assert registry.get_status("fred").consecutive_failures == before + 1


def test_fred_series_csv_valido_es_exito(monkeypatch):
    """Fixture autentico: primeras lineas reales de
    GET https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL
    (verificado en vivo el 2026-10-31)."""

    def handler(request):
        return httpx.Response(200, text="observation_date,CPIAUCSL\n1947-01-01,21.480\n1947-02-01,21.620\n")

    registry = get_data_source_registry()
    registry.record_failure("fred", "fallo previo")
    client = fred.FREDClient(client=_client(handler))
    data = asyncio.run(client.series_csv("CPIAUCSL"))
    assert data["observations"][0]["value"] == "21.620"  # mas reciente primero
    assert registry.get_status("fred").consecutive_failures == 0
