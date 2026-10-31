"""Bugs de parsers: éxito registrado ANTES de validar el contenido (finnhub, ecb).

Un 200 con forma inválida (lista donde iba un objeto, XML sin la divisa base,
tasa no decimal) marcaba la fuente healthy mientras el consumidor rompía:
el panel de salud mentía justo cuando la fuente se degradaba de verdad.
"""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest

from app.services.connectors import ecb, finnhub
from app.services.data_source_health import DataSourceHealthRegistry, get_data_source_registry


@pytest.fixture(autouse=True)
def fresh_registry():
    DataSourceHealthRegistry._instance = None
    yield
    DataSourceHealthRegistry._instance = None


def _failures(key: str) -> int:
    return get_data_source_registry().get_status(key).consecutive_failures


# ---------- Finnhub ----------


class _FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _patch_finnhub(monkeypatch, payload):
    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            return _FakeResponse(payload)

    monkeypatch.setattr(finnhub.httpx, "AsyncClient", _FakeAsyncClient)


def _finnhub_client(monkeypatch, payload):
    _patch_finnhub(monkeypatch, payload)
    client = finnhub.FinnhubClient()
    monkeypatch.setattr(client.settings, "finnhub_api_key", "test-key")
    return client


def test_finnhub_quote_200_lista_no_es_exito(monkeypatch):
    client = _finnhub_client(monkeypatch, [{"c": 1}])
    before = _failures("finnhub")
    with pytest.raises(RuntimeError, match="invalid quote"):
        asyncio.run(client.quote("AAPL", max_retries=0))
    assert _failures("finnhub") == before + 1


def test_finnhub_metric_sin_clave_metric_no_es_exito(monkeypatch):
    client = _finnhub_client(monkeypatch, {"otra": "cosa"})
    before = _failures("finnhub")
    with pytest.raises(RuntimeError, match="invalid metrics"):
        asyncio.run(client.metric("AAPL"))
    assert _failures("finnhub") == before + 1


def test_finnhub_quote_objeto_valido_cierra(monkeypatch):
    client = _finnhub_client(monkeypatch, {"c": 182.5, "t": 1761868800})
    registry = get_data_source_registry()
    registry.record_failure("finnhub", "fallo previo")
    out = asyncio.run(client.quote("AAPL", max_retries=0))
    assert out["c"] == 182.5
    assert _failures("finnhub") == 0


# ---------- ECB ----------


def _patch_ecb(monkeypatch, content: bytes):
    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            return httpx.Response(200, content=content, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(ecb.httpx, "AsyncClient", _FakeAsyncClient)


_XML_SIN_BASE = b"""<?xml version="1.0"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-05-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube><Cube time="2026-10-30"><Cube currency="USD" rate="1.0850"/></Cube></Cube>
</gesmes:Envelope>"""

_XML_TASA_INVALIDA = b"""<?xml version="1.0"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-05-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube><Cube time="2026-10-30"><Cube currency="USD" rate="N/A"/></Cube></Cube>
</gesmes:Envelope>"""

_XML_SIN_FECHA = b"""<?xml version="1.0"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-05-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube><Cube><Cube currency="USD" rate="1.0850"/></Cube></Cube>
</gesmes:Envelope>"""


def test_ecb_xml_sin_divisa_base_no_es_exito(monkeypatch):
    # Base GBP: el XML solo trae USD/EUR implícita -> falta la base pedida.
    _patch_ecb(monkeypatch, _XML_SIN_BASE)
    before = _failures("ecb")
    with pytest.raises(RuntimeError):
        asyncio.run(ecb.ECBClient().conversion_rates(base_currency="GBP", quote_currencies={"USD"}))
    assert _failures("ecb") == before + 1


def test_ecb_tasa_no_decimal_no_es_exito(monkeypatch):
    _patch_ecb(monkeypatch, _XML_TASA_INVALIDA)
    before = _failures("ecb")
    with pytest.raises(RuntimeError):
        asyncio.run(ecb.ECBClient().conversion_rates(base_currency="EUR", quote_currencies={"USD"}))
    assert _failures("ecb") == before + 1


def test_ecb_xml_sin_fecha_no_es_exito(monkeypatch):
    _patch_ecb(monkeypatch, _XML_SIN_FECHA)
    before = _failures("ecb")
    with pytest.raises(RuntimeError):
        asyncio.run(ecb.ECBClient().conversion_rates(base_currency="EUR", quote_currencies={"USD"}))
    assert _failures("ecb") == before + 1


def test_ecb_xml_valido_cierra(monkeypatch):
    _patch_ecb(monkeypatch, _XML_SIN_BASE)  # EUR sí está (implícita): válido para base EUR
    registry = get_data_source_registry()
    registry.record_failure("ecb", "fallo previo")
    rates = asyncio.run(ecb.ECBClient().conversion_rates(base_currency="EUR", quote_currencies={"USD"}))
    assert rates.rate_date == date(2026, 10, 30)
    assert _failures("ecb") == 0


# ---------- Finnhub: 200 {"error": ...} ----------


def test_finnhub_quote_200_con_error_no_es_exito(monkeypatch):
    client = _finnhub_client(monkeypatch, {"error": "Invalid API key"})
    before = _failures("finnhub")
    with pytest.raises(RuntimeError, match="Invalid API key"):
        asyncio.run(client.quote("AAPL", max_retries=0))
    assert _failures("finnhub") == before + 1


def test_finnhub_metric_200_con_error_no_es_exito(monkeypatch):
    client = _finnhub_client(monkeypatch, {"error": "API limit reached"})
    before = _failures("finnhub")
    with pytest.raises(RuntimeError, match="API limit reached"):
        asyncio.run(client.metric("AAPL"))
    assert _failures("finnhub") == before + 1


# ---------- ECB: tasas no finitas o no positivas ----------


def _xml_con_tasa(tasa: str) -> bytes:
    return f"""<?xml version="1.0"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-05-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube><Cube time="2026-10-30"><Cube currency="USD" rate="{tasa}"/></Cube></Cube>
</gesmes:Envelope>""".encode()


@pytest.mark.parametrize("tasa", ["NaN", "Infinity", "-Infinity", "0", "-1.05"])
def test_ecb_tasa_no_finita_o_no_positiva_no_es_exito(monkeypatch, tasa):
    # Decimal() parsea NaN/Infinity sin error: sin la comprobacion colarian.
    _patch_ecb(monkeypatch, _xml_con_tasa(tasa))
    before = _failures("ecb")
    with pytest.raises(RuntimeError):
        asyncio.run(ecb.ECBClient().conversion_rates(base_currency="EUR", quote_currencies={"USD"}))
    assert _failures("ecb") == before + 1
