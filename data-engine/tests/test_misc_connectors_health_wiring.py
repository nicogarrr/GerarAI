"""Cableado al registry de salud de RSS, IR y CelesTrak (VAL-DATA-004).

Expected Behavior:
- 5xx/401/403/429/red degradan; 400/404/410 (recurso concreto retirado) neutros
- Un 200 no basta: sin formato válido (feed RSS/Atom, página HTML, catálogo
  CelesTrak con esquema) se registra fallo de formato y NO éxito
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.services.connectors import celestrak_ast, celestrak_ast_supgp
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


def test_registry_incluye_rss_ir_celestrak():
    sources = get_data_source_registry().sources
    assert {"rss", "ir", "celestrak"} <= set(sources)


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


# ---------- CelesTrak ----------

_NOW = datetime.now(UTC)
_EPOCH = (_NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z")
_GP_ROW = {
    "NORAD_CAT_ID": 1,
    "OBJECT_NAME": "BLUEWALKER-3",
    "OBJECT_ID": "2022-111A",
    "EPOCH": _EPOCH,
    "MEAN_MOTION": 15.0,
    "ECCENTRICITY": 0.001,
    "INCLINATION": 53.0,
    "RA_OF_ASC_NODE": 100.0,
    "ARG_OF_PERICENTER": 90.0,
    "MEAN_ANOMALY": 10.0,
    "BSTAR": 0.0001,
    "MEAN_MOTION_DOT": 0.0,
    "MEAN_MOTION_DDOT": 0.0,
}


def test_celestrak_500_degrada():
    def handler(request):
        return httpx.Response(500, text="")

    before = _failures("celestrak")
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(celestrak_ast.fetch_catalog(_client(handler), fetched_at=_NOW))
    assert _failures("celestrak") == before + 1


def test_celestrak_404_grupo_no_degrada():
    def handler(request):
        return httpx.Response(404, text="")

    before = _failures("celestrak")
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(celestrak_ast.fetch_catalog(_client(handler), fetched_at=_NOW))
    assert _failures("celestrak") == before


def test_celestrak_200_no_json_no_es_exito():
    def handler(request):
        return httpx.Response(200, text="<html><body>challenge</body></html>")

    before = _failures("celestrak")
    with pytest.raises(ValueError):
        asyncio.run(celestrak_ast.fetch_catalog(_client(handler), fetched_at=_NOW))
    assert _failures("celestrak") == before + 1


def test_celestrak_catalogo_valido_cierra():
    def handler(request):
        return httpx.Response(200, json=[_GP_ROW])

    registry = get_data_source_registry()
    registry.record_failure("celestrak", "fallo previo")
    catalog = asyncio.run(celestrak_ast.fetch_catalog(_client(handler), fetched_at=_NOW))
    assert catalog[0]["object_name"] == "BLUEWALKER-3"
    assert _failures("celestrak") == 0


def test_celestrak_supgp_procedencia_invalida_degrada():
    bad = dict(_GP_ROW, CLASSIFICATION_TYPE="U", DATA_SOURCE="OTRA")

    def handler(request):
        return httpx.Response(200, json=[bad])

    before = _failures("celestrak")
    with pytest.raises(ValueError):
        asyncio.run(celestrak_ast_supgp.fetch_supgp(None, _client(handler), fetched_at=_NOW))
    assert _failures("celestrak") == before + 1


def test_celestrak_supgp_valido_cierra():
    row = dict(_GP_ROW, CLASSIFICATION_TYPE="C", DATA_SOURCE="AST-E")

    def handler(request):
        return httpx.Response(200, json=[row])

    registry = get_data_source_registry()
    registry.record_failure("celestrak", "fallo previo")
    out = asyncio.run(celestrak_ast_supgp.fetch_supgp(None, _client(handler), fetched_at=_NOW))
    assert len(out) == 1
    assert _failures("celestrak") == 0
