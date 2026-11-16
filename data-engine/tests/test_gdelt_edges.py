"""Ramas de borde del cliente GDELT (cobertura por fichero, auditor 16-nov-2026)."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.connectors import gdelt as g


@pytest.fixture
def sin_throttle(monkeypatch):
    async def _no_throttle(self):
        pass

    monkeypatch.setattr(g.GDELTClient, "_throttle", _no_throttle)
    g.GDELTClient._blocked_until = 0.0
    yield
    g.GDELTClient._blocked_until = 0.0


# ---------- _gdelt_datetime ----------


def test_gdelt_datetime_vacio_o_invalido():
    assert g._gdelt_datetime(None) is None
    assert g._gdelt_datetime("") is None
    assert g._gdelt_datetime("basura sin formato") is None


def test_gdelt_datetime_ambos_formatos():
    assert g._gdelt_datetime("20261030T153000Z") == datetime(2026, 10, 30, 15, 30, tzinfo=UTC)
    assert g._gdelt_datetime("2026-10-30T15:30:00Z") == datetime(2026, 10, 30, 15, 30, tzinfo=UTC)


# ---------- Retry-After como HTTP-date ----------


def test_retry_after_http_date_naive_se_aware():
    response = httpx.Response(429, headers={"Retry-After": "Fri, 16 Nov 2100 07:28:00"})
    value = g.GDELTClient._raw_retry_after(response)
    assert value is not None and value > 0


def test_retry_after_fecha_pasada_da_cero():
    response = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert g.GDELTClient._raw_retry_after(response) == 0.0


def test_retry_after_invalido_devuelve_none():
    response = httpx.Response(429, headers={"Retry-After": "@@@no-es-fecha@@@"})
    assert g.GDELTClient._raw_retry_after(response) is None


# ---------- news_search sin cliente inyectado ----------


def test_news_search_sin_cliente_crea_uno_efimero(sin_throttle, monkeypatch):
    real_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"articles": []}))
    )

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return real_client

        async def __aexit__(self, *args):
            await real_client.aclose()

    monkeypatch.setattr(g.httpx, "AsyncClient", _FakeAsyncClient)
    result = asyncio.run(g.GDELTClient().news_search("iberdrola"))
    assert result == {"articles": []}


# ---------- poll: filtrado de articulos ----------


def test_poll_descarta_no_dict_idioma_no_soportado_y_duplicados():
    """El bucle de poll es defensivo: news_search ya valida dicts, asi que las
    ramas de descarte solo se alcanzan con un cliente que devuelva crudo."""

    class _StubClient(g.GDELTClient):
        def __init__(self):
            pass

        async def news_search(self, query, max_records=50):
            return {
                "articles": [
                    None,
                    "no-es-dict",
                    {"url": "https://x.test/1", "title": "Uno", "language": "Russian"},
                    {"url": "", "title": ""},
                    {"url": "https://x.test/2", "title": "Dos", "language": "English"},
                    {"url": "https://x.test/2", "title": "Duplicada de Dos"},
                    {"url": "https://x.test/3", "title": "Tres"},
                ]
            }

    result = asyncio.run(g.GDELTConnector(_StubClient()).poll("iberdrola"))
    assert result.status == "ok"
    titles = [item.title for item in result.items]
    assert titles == ["Dos", "Tres"]


# ---------- fabrica de cliente Redis ----------


def test_redis_factory_sin_redis_devuelve_none(monkeypatch):
    monkeypatch.setattr(g, "get_settings", MagicMock(side_effect=RuntimeError("sin settings")))
    assert g._gdelt_redis_client() is None
