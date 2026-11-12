"""Cableado al registry de salud de RSS e IR (VAL-DATA-004).

Expected Behavior:
- 5xx/401/403/429/red degradan; 400/404/410 (recurso concreto retirado) neutros
- Un 200 no basta: sin formato válido (feed RSS/Atom, página HTML) se
  registra fallo de formato y NO éxito
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.connectors.ir import IRConnector
from app.services.connectors.rss import RSSConnector
from app.services.data_source_health import DataSourceHealthRegistry, get_data_source_registry


@pytest.fixture(autouse=True)
def fresh_registry():
    DataSourceHealthRegistry._instance = None
    yield
    DataSourceHealthRegistry._instance = None


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _failures(key: str) -> int:
    return get_data_source_registry().get_status(key).consecutive_failures


# ---------- RSS ----------


def test_registry_incluye_rss_ir():
    sources = get_data_source_registry().sources
    assert {"rss", "ir"} <= set(sources)


def test_rss_500_degrada():
    def handler(request):
        return httpx.Response(500, text="")

    before = _failures("rss")
    result = asyncio.run(RSSConnector(client=_client(handler)).poll("https://feed.example.com/rss"))
    assert result.items == []
    assert _failures("rss") == before + 1


def test_rss_404_feed_retirado_no_degrada():
    def handler(request):
        return httpx.Response(404, text="")

    before = _failures("rss")
    asyncio.run(RSSConnector(client=_client(handler)).poll("https://feed.example.com/rss"))
    assert _failures("rss") == before


def test_rss_200_html_challenge_no_es_exito():
    def handler(request):
        return httpx.Response(200, text="<html><head><title>Request Rejected</title></head></html>")

    before = _failures("rss")
    asyncio.run(RSSConnector(client=_client(handler)).poll("https://feed.example.com/rss"))
    assert _failures("rss") == before + 1


def test_rss_feed_valido_cierra():
    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>Test Feed</title>'
        "<item><title>Noticia</title><link>https://example.com/1</link></item>"
        "</channel></rss>"
    )

    def handler(request):
        return httpx.Response(200, text=rss)

    registry = get_data_source_registry()
    registry.record_failure("rss", "fallo previo")
    result = asyncio.run(RSSConnector(client=_client(handler)).poll("https://feed.example.com/rss"))
    assert len(result.items) == 1
    assert _failures("rss") == 0


# ---------- IR ----------


def test_ir_500_degrada():
    def handler(request):
        return httpx.Response(503, text="")

    before = _failures("ir")
    result = asyncio.run(IRConnector(client=_client(handler)).poll("https://ir.example.com/"))
    assert result.items == []
    assert _failures("ir") == before + 1


def test_ir_404_pagina_retirada_no_degrada():
    def handler(request):
        return httpx.Response(404, text="")

    before = _failures("ir")
    asyncio.run(IRConnector(client=_client(handler)).poll("https://ir.example.com/"))
    assert _failures("ir") == before


def test_ir_200_sin_html_no_es_exito():
    def handler(request):
        return httpx.Response(
            200, text='{"error": "rate limited"}', headers={"content-type": "application/json"}
        )

    before = _failures("ir")
    asyncio.run(IRConnector(client=_client(handler)).poll("https://ir.example.com/"))
    assert _failures("ir") == before + 1


def test_ir_pagina_valida_cierra():
    def handler(request):
        return httpx.Response(200, text="<html><body><a href='/press/1'>Press release</a></body></html>")

    registry = get_data_source_registry()
    registry.record_failure("ir", "fallo previo")
    result = asyncio.run(IRConnector(client=_client(handler)).poll("https://ir.example.com/"))
    assert result.errors == []
    assert _failures("ir") == 0
