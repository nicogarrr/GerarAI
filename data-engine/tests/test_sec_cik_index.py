"""Busqueda ticker -> CIK con el mapa de la SEC ya en cache.

Antes cada ``cik_for_ticker`` hacia deepcopy de ``company_tickers.json``
(~10.000 emisores) y lo recorria entero: el calendario de catalizadores
tardaba ~0,9 s por carga con la cache caliente y sin ninguna peticion de red.
Ahora el indice se construye una vez por entrada de cache, con la misma
politica que ``match_cik`` (exacto primero; normalizado solo si es unico).
"""

import asyncio
import copy

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.connectors import sec
from app.services.sec_ticker import normalize_sec_ticker

MAP = {
    str(i): {"cik_str": 1000 + i, "ticker": t, "title": t}
    for i, t in enumerate(
        ["AAPL", "BRK-B", "BRK-A", "MSFT", "GOOG", "GOOGL", "BF-B"] + [f"T{n}" for n in range(3000)]
    )
}


def _reference_match(entries, wanted):
    """Algoritmo original de match_cik (antes de #perf2-2), como oraculo."""
    pairs = [(str(t), str(c)) for t, c in entries]
    wanted_upper = wanted.strip().upper()
    for ticker, cik in pairs:
        if ticker.upper() == wanted_upper:
            return cik
    norm = normalize_sec_ticker(wanted_upper)
    matches = {cik for ticker, cik in pairs if normalize_sec_ticker(ticker) == norm}
    return next(iter(matches)) if len(matches) == 1 else None


_TICKER = st.text(alphabet="ABCab.-/ 1", min_size=0, max_size=4)


@settings(max_examples=300, deadline=None)
@given(
    entries=st.lists(st.tuples(_TICKER, st.sampled_from(["1", "2", "3", "4"])), max_size=12),
    wanted=_TICKER,
)
def test_index_matches_original_policy(entries, wanted):
    from app.services.sec_ticker import CikIndex

    assert CikIndex(entries).lookup(wanted) == _reference_match(entries, wanted)


def test_many_lookups_reuse_one_index_without_copying_the_map(monkeypatch):
    sec.reset_sec_client_state()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json=MAP)

    copies = {"n": 0}
    real_deepcopy = copy.deepcopy

    def counting_deepcopy(obj, *a, **k):
        copies["n"] += 1
        return real_deepcopy(obj, *a, **k)

    monkeypatch.setattr(sec.copy, "deepcopy", counting_deepcopy)
    monkeypatch.setattr(sec.sec_edgar, "manifest_cik", lambda ticker: None)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = sec.SECClient(http, use_cache=True, requests_per_second=1000)
            return [
                await client.cik_for_ticker(t)
                for t in ["AAPL", "brk.b", "BRK-A", "MSFT", "BF.B", "NOPE"] * 10
            ]

    try:
        result = asyncio.run(run())
    finally:
        sec.reset_sec_client_state()
    assert result[:6] == ["0000001000", "0000001001", "0000001002", "0000001003", "0000001006", None]
    assert len(requests) == 1
    # Una sola copia (al guardar en cache); antes, una por busqueda (60).
    assert copies["n"] <= 1
