"""Quick win UX 4: el titular SEC se genera en español, sin ticker ni fecha.

La tabla de noticias ya muestra ticker y fecha en columnas propias; un
titular «COST COST 8-K (2026-09-24) SEC 8-K filed 2026-09-24» repetía todo
y llegaba en inglés. El titular es «8-K presentado ante la SEC» y el
summary queda vacío (la frase ya es el titular).
"""
from __future__ import annotations

import httpx

from app.services.async_bridge import run_from_any_context as run_async
from app.services.connectors.sec import SECClient


def _payload() -> dict:
    return {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000123"],
                "form": ["8-K"],
                "filingDate": ["2026-09-24"],
                "reportDate": ["2026-09-20"],
                "primaryDocument": ["current-report.htm"],
            }
        }
    }


def test_titular_sec_en_espanol_sin_ticker_ni_fecha():
    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_payload(), request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sec = SECClient(client=client, requests_per_second=10)
            return await sec.recent_filings("320193", ticker="AAPL")

    result = run_async(probe())
    assert len(result.items) == 1
    item = result.items[0]
    assert item.title == "8-K presentado ante la SEC"
    assert item.summary == ""
    # La fecha sigue estructurada en published_at/metadata, no en el texto.
    assert item.published_at is not None
    assert item.metadata["filing_date"] == "2026-09-24"
    assert item.metadata["report_date"] == "2026-09-20"
    assert item.ticker == "AAPL"
    # La SEC no publica titular del filing: el texto ES es display de GerarAI
    # y no debe persistirse como source_headline (ver test_sec_ingest_provenance).
    assert item.headline_from_source is False
