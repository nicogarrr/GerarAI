"""Bordes de energy_flows: parse_retail_revenue (ano invalido/futuro y sector
desconocido se saltan) y load_revenue (sin API key, cache fresca, corte por
fallo reciente, fallo HTTP marca failed_until, exito rellena cache).

Los años se derivan del reloj de prueba: parse_retail_revenue exige
year < datetime.now(UTC).year y un año fijo haria fallar el test al cambiar
de año natural.
"""

import time
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from app.services import energy_flows

AMOUNTS = {"RES": "200", "COM": "150", "IND": "100", "TRA": "30", "OTH": "20", "ALL": "500"}


def _rows(year: str) -> list[dict]:
    return [
        {"period": year, "stateid": "US", "sectorid": k, "revenue": v, "revenue-units": "million dollars"}
        for k, v in AMOUNTS.items()
    ]


@pytest.fixture
def cache_limpia():
    snapshot = dict(energy_flows._cache)
    energy_flows._cache.clear()
    yield energy_flows._cache
    energy_flows._cache.clear()
    energy_flows._cache.update(snapshot)


def _api_key(monkeypatch, key):
    monkeypatch.setattr(energy_flows, "get_settings", lambda: SimpleNamespace(eia_api_key=key))


def test_parse_salta_ano_invalido_y_ano_futuro():
    valido = datetime.now(UTC).year - 1
    futuro = datetime.now(UTC).year + 1
    data = (
        _rows(str(futuro))
        + _rows(str(valido))
        + [
            {
                "period": "2025x",
                "stateid": "US",
                "sectorid": "RES",
                "revenue": "1",
                "revenue-units": "million dollars",
            }
        ]
    )
    year, sectors, total = energy_flows.parse_retail_revenue(data)
    assert year == str(valido)
    assert len(sectors) == 5
    assert total == 500e6


def test_parse_ignora_sector_desconocido():
    valido = str(datetime.now(UTC).year - 1)
    data = _rows(valido) + [
        {
            "period": valido,
            "stateid": "US",
            "sectorid": "XX",
            "revenue": "999",
            "revenue-units": "million dollars",
        }
    ]
    year, sectors, _total = energy_flows.parse_retail_revenue(data)
    assert year == valido
    assert {row["key"] for row in sectors} == set(energy_flows.SECTORS)


def test_load_sin_api_key_falla_cerrado(monkeypatch, cache_limpia):
    _api_key(monkeypatch, None)
    with pytest.raises(RuntimeError, match="EIA not configured"):
        energy_flows.load_revenue()


def test_load_cache_fresca_no_llama_http(monkeypatch, cache_limpia):
    _api_key(monkeypatch, "K")
    cache_limpia.update(data=("cached", [], 0.0), until=time.monotonic() + 100, failed_until=0)

    def no_http(*args, **kwargs):
        raise AssertionError("no debe llamar a HTTP con cache fresca")

    monkeypatch.setattr(energy_flows.httpx, "get", no_http)
    assert energy_flows.load_revenue() == ("cached", [], 0.0)


def test_load_fallo_reciente_corta_antes_de_http(monkeypatch, cache_limpia):
    _api_key(monkeypatch, "K")
    cache_limpia.update(failed_until=time.monotonic() + 100)

    def no_http(*args, **kwargs):
        raise AssertionError("no debe llamar a HTTP durante el corte")

    monkeypatch.setattr(energy_flows.httpx, "get", no_http)
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        energy_flows.load_revenue()


def test_load_fallo_http_marca_failed_until(monkeypatch, cache_limpia):
    _api_key(monkeypatch, "K")

    def http_roto(*args, **kwargs):
        raise httpx.ConnectError("corte")

    monkeypatch.setattr(energy_flows.httpx, "get", http_roto)
    antes = time.monotonic()
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        energy_flows.load_revenue()
    assert cache_limpia["failed_until"] > antes


def test_load_exito_rellena_cache(monkeypatch, cache_limpia):
    _api_key(monkeypatch, "K")
    valido = str(datetime.now(UTC).year - 1)

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": {"data": _rows(valido)}}

    monkeypatch.setattr(energy_flows.httpx, "get", lambda *args, **kwargs: _Resp())
    year, sectors, total = energy_flows.load_revenue()
    assert year == valido
    assert len(sectors) == 5
    assert total == 500e6
    assert cache_limpia["data"] == (year, sectors, total)
    assert cache_limpia["until"] > time.monotonic()
    assert cache_limpia["failed_until"] == 0
