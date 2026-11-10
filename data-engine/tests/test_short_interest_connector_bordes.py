"""Bordes del conector FINRA short_interest no cubiertos por test_short_interest_connector.

Sin red: httpx.MockTransport (o AsyncClient parcheado para la ruta client=None).
Cubre: cabecera vacia, exento invalido y fecha imposible en RegSHO, HTTP 500/404 y
payload no lista en las dos rutas, argumentos invalidos, presupuesto de peticiones
agotado y bajada binaria (wanted < primer codigo de la pagina).

Nota de cobertura: la guarda `if budget <= 0` de page() (linea 273) es defensiva e
inalcanzable: ambos bucles llamantes ya comprueban `budget > 0`. Se deja sin cubrir
a proposito, como cualquier guarda defensiva muerta.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import httpx

from app.services.connectors import short_interest as si

DAILY = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market \n20261030|ACME|100|10|1000|M\n"


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _registro(code):
    return {
        "symbolCode": code,
        "issueName": code,
        "settlementDate": "2026-10-15",
        "currentShortPositionQuantity": 2000,
        "previousShortPositionQuantity": 1000,
        "averageDailyVolumeQuantity": 500,
        "daysToCoverQuantity": 4,
        "marketClassCode": "Q",
    }


def _registry(monkeypatch):
    reg = MagicMock()
    monkeypatch.setattr(si, "get_data_source_registry", lambda: reg)
    return reg


def test_cabecera_vacia_es_falsa():
    assert si.has_regsho_daily_header("") is False


def test_parse_regsho_exento_mayor_que_corto_se_ignora():
    texto = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market \n20261030|ACME|100|150|1000|M\n"
    assert si.parse_regsho_daily(texto, "ACME") is None


def test_parse_regsho_fecha_imposible_se_ignora():
    texto = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market \n20261340|ACME|100|10|1000|M\n"
    assert si.parse_regsho_daily(texto, "ACME") is None


def test_fetch_short_volume_sin_cliente_crea_uno(monkeypatch):
    real_client = si.httpx.AsyncClient
    monkeypatch.setattr(
        si.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=DAILY))
        ),
    )
    row = asyncio.run(si.fetch_short_volume("ACME", lookback_days=0))
    assert row is not None and row["date"] == "2026-10-30" and row["short_volume"] == 100


def test_fetch_short_volume_http_500_registra_fallo(monkeypatch):
    reg = _registry(monkeypatch)

    async def run():
        async with _client(lambda request: httpx.Response(500, text="boom")) as client:
            return await si.fetch_short_volume("ACME", client=client, lookback_days=0)

    assert asyncio.run(run()) is None
    reg.record_failure.assert_called_once_with(si.REGISTRY_KEY, "HTTP 500")


def test_fetch_short_interest_sin_cliente_crea_uno(monkeypatch):
    real_client = si.httpx.AsyncClient
    monkeypatch.setattr(
        si.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[_registro("ACME")]))
        ),
    )
    hit = asyncio.run(si.fetch_short_interest("ACME"))
    assert hit is not None and hit["symbol"] == "ACME" and hit["short_interest"] == 2000


def test_fetch_short_interest_http_500_registra_fallo(monkeypatch):
    reg = _registry(monkeypatch)

    async def run():
        async with _client(lambda request: httpx.Response(500, text="boom")) as client:
            return await si.fetch_short_interest("ACME", client=client)

    assert asyncio.run(run()) is None
    reg.record_failure.assert_any_call(si.REGISTRY_KEY, "HTTP 500")
    assert {c.args[1] for c in reg.record_failure.call_args_list} == {"HTTP 500"}


def test_fetch_short_interest_http_404_no_es_fallo(monkeypatch):
    reg = _registry(monkeypatch)

    async def run():
        async with _client(lambda request: httpx.Response(404)) as client:
            return await si.fetch_short_interest("ACME", client=client, max_requests=2)

    assert asyncio.run(run()) is None
    reg.record_failure.assert_not_called()


def test_fetch_short_interest_payload_no_lista(monkeypatch):
    reg = _registry(monkeypatch)

    async def run():
        async with _client(lambda request: httpx.Response(200, json={"error": "x"})) as client:
            return await si.fetch_short_interest("ACME", client=client)

    assert asyncio.run(run()) is None
    reg.record_failure.assert_any_call(si.REGISTRY_KEY, "payload no lista")
    assert {c.args[1] for c in reg.record_failure.call_args_list} == {"payload no lista"}


def test_fetch_short_interest_argumentos_invalidos():
    assert asyncio.run(si.fetch_short_interest("  ")) is None
    assert asyncio.run(si.fetch_short_interest("ACME", page_size=0)) is None
    assert asyncio.run(si.fetch_short_interest("ACME", max_requests=0)) is None


def test_fetch_short_interest_presupuesto_agotado():
    async def run():
        async with _client(lambda request: httpx.Response(200, json=[_registro("AAA")])) as client:
            return await si.fetch_short_interest("ZZZ", client=client, max_requests=1)

    assert asyncio.run(run()) is None


def test_fetch_short_interest_hit_en_pagina_exponencial_con_budget_minimo():
    # max_requests=1: el barrido exponencial pide la pagina 1, donde esta el
    # ticker; sin pasar por la binaria lo encuentra en las paginas ya vistas.
    def handler(request):
        offset = int(request.url.params["offset"])
        if offset == 200:
            return httpx.Response(200, json=[_registro("ACME")])
        return httpx.Response(200, json=[_registro("AAA")])

    async def run():
        async with _client(handler) as client:
            return await si.fetch_short_interest("ACME", client=client, max_requests=1)

    hit = asyncio.run(run())
    assert hit is not None and hit["symbol"] == "ACME"


def test_fetch_short_interest_frena_cuando_la_pagina_alcanza_el_ticker():
    # Ultimo symbolCode de la pagina == ticker: frena sin pedir la pagina 2.
    offsets = []

    def handler(request):
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        if offset == 200:
            return httpx.Response(200, json=[_registro("ACME")])
        if offset == 0:
            return httpx.Response(200, json=[_registro("AAA")])
        return httpx.Response(200, json=[])

    async def run():
        async with _client(handler) as client:
            return await si.fetch_short_interest("ACME", client=client)

    hit = asyncio.run(run())
    assert hit is not None and hit["symbol"] == "ACME"
    assert sorted(offsets) == [0, 200]


def test_fetch_short_interest_binaria_baja_y_barre_paginas_vistas():
    def handler(request):
        offset = int(request.url.params["offset"])
        if offset == 0:
            return httpx.Response(200, json=[_registro("BBB")])
        return httpx.Response(200, json=[_registro("AAA"), _registro("BBB")])

    async def run():
        async with _client(handler) as client:
            return await si.fetch_short_interest("AAA", client=client)

    hit = asyncio.run(run())
    assert hit is not None and hit["symbol"] == "AAA" and hit["previous_short_interest"] == 1000
