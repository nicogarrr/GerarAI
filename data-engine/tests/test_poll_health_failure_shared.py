"""Registro de salud compartido de conectores de sondeo (ir, rss).

ir.py y rss.py traian _record_health_failure copiada a caracter; ahora vive
en connectors.base.record_poll_health_failure. Fija su comportamiento y que
ninguno reintroduce su copia.
"""

from pathlib import Path

import httpx

import app.services.connectors.base as base
from app.services.connectors.base import record_poll_health_failure


class _RegistrySpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def record_failure(self, key: str, reason: str) -> None:
        self.calls.append((key, reason))


def _spy(monkeypatch):
    spy = _RegistrySpy()
    monkeypatch.setattr(base, "get_data_source_registry", lambda: spy)
    return spy


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://ejemplo.test/x")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_recurso_retirado_es_neutro(monkeypatch):
    spy = _spy(monkeypatch)
    for status in (400, 404, 410):
        record_poll_health_failure("k", _http_error(status))
    assert spy.calls == []


def test_otro_status_degrada(monkeypatch):
    spy = _spy(monkeypatch)
    record_poll_health_failure("k", _http_error(503))
    assert spy.calls == [("k", "HTTP 503")]


def test_error_de_red_degrada(monkeypatch):
    spy = _spy(monkeypatch)
    record_poll_health_failure("k", httpx.ConnectError("caida"))
    assert spy.calls == [("k", "error de red: ConnectError")]


def test_documento_invalido_degrada(monkeypatch):
    spy = _spy(monkeypatch)
    record_poll_health_failure("k", ValueError("xml roto"))
    assert spy.calls == [("k", "documento inválido: ValueError")]


def test_ir_y_rss_usan_el_helper_sin_copias():
    root = Path(__file__).resolve().parents[1]
    for nombre in ("ir.py", "rss.py"):
        src = (root / "app" / "services" / "connectors" / nombre).read_text(encoding="utf-8")
        assert "record_poll_health_failure(_REGISTRY_KEY, exc)" in src, nombre
        assert "_record_health_failure" not in src, nombre
        assert "documento inválido" not in src, nombre
