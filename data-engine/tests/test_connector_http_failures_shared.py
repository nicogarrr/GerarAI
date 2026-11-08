"""Cascada compartida de registro de fallos HTTP de conectores.

finnhub, fred, openfigi y fmp traian copiado el mismo trio de except
(HTTPStatusError con 400/404 de paso, TransportError, ValueError -> registry).
Ahora vive en connectors.base.record_connector_http_failures; este test fija
su comportamiento exacto y que ningun conector reintroduce su copia.
"""

from pathlib import Path

import httpx
import pytest

from app.services.connectors.base import record_connector_http_failures


class _RegistrySpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def record_failure(self, key: str, reason: str) -> None:
        self.calls.append((key, reason))


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://ejemplo.test/x")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_passthrough_no_registra_y_relanza():
    spy = _RegistrySpy()
    with pytest.raises(httpx.HTTPStatusError):
        with record_connector_http_failures(spy, "k"):
            raise _http_error(404)
    assert spy.calls == []


def test_otro_status_registra_y_relanza():
    spy = _RegistrySpy()
    with pytest.raises(httpx.HTTPStatusError):
        with record_connector_http_failures(spy, "k"):
            raise _http_error(500)
    assert spy.calls == [("k", "HTTP 500")]


def test_passthrough_personalizable():
    spy = _RegistrySpy()
    with pytest.raises(httpx.HTTPStatusError):
        with record_connector_http_failures(spy, "k", passthrough_statuses=(400, 402, 404)):
            raise _http_error(402)
    assert spy.calls == []


def test_error_de_red_registra_y_relanza():
    spy = _RegistrySpy()
    with pytest.raises(httpx.TransportError):
        with record_connector_http_failures(spy, "k"):
            raise httpx.ConnectError("caida")
    assert spy.calls == [("k", "error de red: ConnectError")]


def test_no_json_registra_y_relanza():
    spy = _RegistrySpy()
    with pytest.raises(ValueError):
        with record_connector_http_failures(spy, "k"):
            raise ValueError("json roto")
    assert spy.calls == [("k", "respuesta no JSON")]


def test_otras_excepciones_pasan_sin_registrar():
    spy = _RegistrySpy()
    with pytest.raises(RuntimeError):
        with record_connector_http_failures(spy, "k"):
            raise RuntimeError("otra cosa")
    assert spy.calls == []


CONNECTORES = ["finnhub.py", "fred.py", "openfigi.py", "fmp.py"]

# Variantes que NO son la cascada completa y se quedan como estaban:
# - fred.series_csv: endpoint CSV, no parsea JSON (sin rama ValueError).
# - openfigi.map_identifier_sync: solo envuelve response.json() (solo ValueError).
EXCEPCIONES_HTTPSTATUS = {"fred.py": 1}
EXCEPCIONES_NO_JSON = {"openfigi.py": 1}


def test_los_conectores_usan_la_cascada_compartida_sin_copias():
    conndir = Path(__file__).resolve().parent.parent / "app" / "services" / "connectors"
    for nombre in CONNECTORES:
        src = (conndir / nombre).read_text(encoding="utf-8")
        assert "record_connector_http_failures(registry, REGISTRY_KEY" in src, nombre
        assert src.count("except httpx.HTTPStatusError") == EXCEPCIONES_HTTPSTATUS.get(nombre, 0), nombre
        assert src.count('"respuesta no JSON"') == EXCEPCIONES_NO_JSON.get(nombre, 0), nombre
