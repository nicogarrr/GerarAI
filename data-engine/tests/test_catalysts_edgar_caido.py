"""Catalizadores con EDGAR caido: las cargas siguientes no vuelven a esperar.

Con mas de MAX_DEADLINE_TICKERS emisores US, cada carga probaba los 60
siguientes que aun no habian fallado y esperaba otra vez el presupuesto
(~8 s en /api/calendar/catalysts). Si en una carga ningun emisor responde
porque la red falla, EDGAR esta caido: durante la memoria de fallos el resto
se declara «EDGAR no disponible» al momento, sin red. Un emisor sin CIK no
es EDGAR caido.
"""

import asyncio
from datetime import date

import pytest

from app.services import catalyst_calendar_service as svc


@pytest.fixture(autouse=True)
def _reset():
    svc._FAILED_UNTIL.clear()
    yield
    svc._FAILED_UNTIL.clear()


def _run(tickers, cik, subs):
    return asyncio.run(
        svc.fetch_filing_deadlines(
            set(tickers), date(2026, 1, 1), date(2026, 12, 31), cik_fetcher=cik, submissions_fetcher=subs
        )
    )


TICKERS = [f"T{i:03d}" for i in range(150)]


def test_edgar_caido_la_segunda_carga_no_consulta_nada():
    calls = []

    async def cik(t):
        calls.append(t)
        raise OSError("red caida")

    async def subs(c):
        return {}

    first = _run(TICKERS, cik, subs)
    assert first["status"] == "unavailable"
    assert 0 < len(calls) <= svc.MAX_DEADLINE_TICKERS
    calls.clear()
    second = _run(TICKERS, cik, subs)
    assert calls == []
    assert second["status"] == "unavailable"
    assert second["events"] == []
    assert second["errors"] == [f"Plazos 10-Q/10-K: EDGAR no disponible para {t}" for t in TICKERS]


def test_emisores_sin_cik_no_marcan_edgar_caido():
    calls = []

    async def cik(t):
        calls.append(t)
        return None

    async def subs(c):
        return {}

    _run(TICKERS, cik, subs)
    calls.clear()
    _run(TICKERS, cik, subs)
    assert len(calls) == svc.MAX_DEADLINE_TICKERS  # sigue probando los siguientes


def test_con_un_emisor_que_responde_no_se_marca_caido():
    calls = []

    async def cik(t):
        calls.append(t)
        if t == "T000":
            return "1"
        raise OSError("red caida")

    async def subs(c):
        return {"filings": {"recent": {}}}

    _run(TICKERS, cik, subs)
    calls.clear()
    _run(TICKERS, cik, subs)
    assert calls  # EDGAR responde a medias: se sigue consultando
