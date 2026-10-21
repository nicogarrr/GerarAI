"""Material SEC de eventos de resultados: emparejado, periodo, clasificacion y ausencia honesta.

Las estructuras reproducen respuestas reales de data.sec.gov / sec.gov (TSLA, META y ASTS,
21-oct-2026). Red siempre inyectada.
"""

import asyncio
from datetime import date

from app.services import earnings_materials_service as svc

TSLA = {
    "filings": {
        "recent": {
            "form": ["8-K", "8-K", "10-Q"],
            "items": ["2.02,9.01", "2.02,9.01", ""],
            "filingDate": ["2026-10-02", "2026-07-22", "2026-07-23"],
            "accessionNumber": ["0001628280-26-064366", "0001628280-26-049213", "0001628280-26-049500"],
        }
    }
}
INDEX = (
    "<table>"
    "<tr><td>1</td><td>8-K</td><td><a href='/x'>tsla-20260722.htm</a> iXBRL</td><td>8-K</td></tr>"
    "<tr><td>2</td><td>EX-99.1</td><td><a href='/x'>exhibit991.htm</a></td><td>EX-99.1</td></tr>"
    "<tr><td>3</td><td>EX-99.2</td><td><a href='/x'>deck.htm</a></td><td>EX-99.2</td></tr>"
    "<tr><td>4</td><td>GRAPHIC</td><td>a.jpg</td><td>GRAPHIC</td></tr>"
    "<tr><td>5</td><td>EX-99.3</td><td>../../evil.htm</td><td>EX-99.3</td></tr>"
    "</table>"
)


class FakeSEC:
    def __init__(self, submissions=None, docs=None, cik="0001318605", fail=()):
        self._submissions = submissions
        self._docs = docs or {}
        self._cik = cik
        self.fail = set(fail)

    @staticmethod
    def filing_index_url(cik, accession):
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"

    async def cik_for_ticker(self, ticker):
        if "cik" in self.fail:
            raise RuntimeError("red")
        return self._cik

    async def submissions(self, cik):
        if "submissions" in self.fail:
            raise RuntimeError("403")
        return self._submissions

    async def filing_document(self, url):
        name = url.rsplit("/", 1)[-1]
        if name in self.fail or name not in self._docs:
            raise RuntimeError("fallo")
        return self._docs[name].encode(), "text/html"

    async def filing_document_head(self, url, max_bytes=32768):
        raw, _ = await self.filing_document(url)
        return raw[:max_bytes]


def _run(sec, event_date, label="Jun/2026", confirmed=True):
    return asyncio.run(
        svc.resolve_materials(sec=sec, ticker="TSLA", event_date=event_date, fiscal_label=label, confirmed=confirmed)
    )


def test_matches_by_date_window_not_latest_2_02():
    assert svc.pick_results_filing(TSLA, date(2026, 10, 21)) is None  # el 2.02 del 2-oct es produccion/entregas
    assert svc.pick_results_filing(TSLA, date(2026, 7, 22))["accession"] == "0001628280-26-049213"
    assert svc.pick_results_filing(TSLA, date(2026, 7, 21))["accession"] == "0001628280-26-049213"
    assert svc.pick_results_filing(TSLA, date(2026, 7, 19)) is None


def test_items_with_spaces_are_matched():
    subs = {"filings": {"recent": {"form": ["8-K"], "items": ["8.01, 2.02"], "filingDate": ["2026-07-22"],
                                   "accessionNumber": ["0001-26-1"]}}}
    assert svc.pick_results_filing(subs, date(2026, 7, 22))["accession"] == "0001-26-1"


def test_index_only_simple_exhibit_filenames():
    assert svc.parse_filing_index(INDEX) == [
        {"type": "EX-99.1", "filename": "exhibit991.htm"},
        {"type": "EX-99.2", "filename": "deck.htm"},
    ]


def test_classification_by_real_headings():
    assert svc.classify_exhibit("EX-99.1 PRESS RELEASE AST SpaceMobile Provides Business Update and Second Quarter 2026 Results") == "nota_prensa"
    assert svc.classify_exhibit("EX-99.2 BUSINESS UPDATE Second Quarter 2026 August 10, 2026") == "presentacion"
    assert svc.classify_exhibit("Q2 2026 Update 1 Exhibit 99.1 Highlights 03 Financial Summary") == "presentacion"
    assert svc.classify_exhibit("Meta Reports Second Quarter 2026 Results MENLO PARK") == "nota_prensa"
    assert svc.classify_exhibit("Exhibit 99.1 Tesla Q3 production and deliveries") == "documento"


def test_period_confirms_contradicts_or_does_not_assert():
    assert svc.check_period("for the quarter ended September 30, 2026", "Sep/2026") == "confirmado"
    assert svc.check_period("Q2 2026 Update Highlights", "Jun/2026") == "confirmado"
    assert svc.check_period("BUSINESS UPDATE Second Quarter 2026", "Jun/2026") == "confirmado"
    assert svc.check_period("quarter ended June 30, 2026", "Sep/2026") == "contradice"
    assert svc.check_period("Second Quarter 2025 results", "Jun/2026") == "no_verificado"
    assert svc.check_period("Highlights", None) == "no_verificado"


def test_ok_links_only_period_confirmed_documents():
    sec = FakeSEC(TSLA, {
        "0001628280-26-049213-index.htm": INDEX,
        "exhibit991.htm": "Q2 2026 Update Highlights Financial Summary",
        "deck.htm": "Highlights without any period",
    })
    result = _run(sec, date(2026, 7, 22))
    assert result["status"] == "ok" and result["filed_at"] == "2026-07-22"
    assert [(d["exhibit"], d["kind"]) for d in result["documents"]] == [("EX-99.1", "presentacion")]
    assert result["documents"][0]["url"] == "https://www.sec.gov/Archives/edgar/data/1318605/000162828026049213/exhibit991.htm"


def test_no_filing_after_good_read_but_failures_are_not_absence():
    assert _run(FakeSEC(TSLA), date(2026, 10, 21))["status"] == "sin_filing"
    assert _run(FakeSEC(TSLA, fail=["submissions"]), date(2026, 10, 21))["status"] == "no_disponible"
    assert _run(FakeSEC(TSLA, fail=["cik"]), date(2026, 10, 21))["status"] == "no_disponible"
    index_down = FakeSEC(TSLA, {})
    assert _run(index_down, date(2026, 7, 22))["status"] == "no_disponible"
    partial = FakeSEC({**TSLA, "_fallback": True})
    assert _run(partial, date(2026, 7, 22))["status"] == "no_disponible"


def test_unreadable_exhibit_is_not_memoized_as_valid():
    sec = FakeSEC(TSLA, {"0001628280-26-049213-index.htm": INDEX}, fail=["exhibit991.htm", "deck.htm"])
    assert _run(sec, date(2026, 7, 22)) is None


def test_estimated_foreign_and_unknown_issuers_assert_nothing():
    assert _run(FakeSEC(TSLA), date(2026, 7, 22), confirmed=False)["status"] == "sin_cobertura_sec"
    bn = {"filings": {"recent": {"form": ["6-K", "40-F"], "items": ["", ""], "filingDate": ["2026-08-13", "2026-03-01"],
                                 "accessionNumber": ["a", "b"]}}}
    assert _run(FakeSEC(bn), date(2026, 8, 13))["status"] == "sin_cobertura_sec"
    assert _run(FakeSEC(None, cik=None), date(2026, 8, 13))["status"] == "sin_cobertura_sec"


def test_period_mismatch_links_nothing_and_cache_skips_unfinished():
    sec = FakeSEC(TSLA, {"0001628280-26-049213-index.htm": INDEX,
                         "exhibit991.htm": "results for the quarter ended March 31, 2026", "deck.htm": "Highlights"})
    assert _run(sec, date(2026, 7, 22))["status"] == "periodo_no_coincide"
    svc.reset_cache()
    events = [{"ticker": "TSLA", "date": "2026-07-22", "fiscal_label": "Jun/2026", "confirmed": True},
              {"ticker": "OLD", "date": "2026-06-01", "fiscal_label": "Mar/2026", "confirmed": True}]
    out = asyncio.run(svc.materials_for_events(events, date(2026, 7, 24), sec=FakeSEC(TSLA, fail=["submissions"])))
    assert list(out) == ["TSLA|2026-07-22"] and out["TSLA|2026-07-22"]["status"] == "no_disponible"
    svc.reset_cache()


def test_budget_is_below_the_frontend_15s_client_timeout():
    assert svc.TOTAL_BUDGET_S < 15


def test_slow_events_return_partial_instead_of_losing_everything():
    class Slow(FakeSEC):
        async def submissions(self, cik):
            await asyncio.sleep(5)
            return self._submissions

    svc.reset_cache()
    old = svc.TOTAL_BUDGET_S
    svc.TOTAL_BUDGET_S = 0.2
    try:
        events = [{"ticker": "TSLA", "date": "2026-07-22", "fiscal_label": "Jun/2026", "confirmed": True}]
        out = asyncio.run(svc.materials_for_events(events, date(2026, 7, 24), sec=Slow(TSLA)))
    finally:
        svc.TOTAL_BUDGET_S = old
    assert out == {}


def test_head_reader_stops_at_the_cap_and_rejects_non_sec_hosts():
    import httpx
    import pytest

    from app.services.connectors.sec import SECClient

    big = b"<html>" + b"x" * 1_000_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sec = SECClient(client=client, requests_per_second=10)
            head = await sec.filing_document_head("https://www.sec.gov/Archives/edgar/data/1/2/x.htm", 1000)
            assert len(head) == 1000 and head.startswith(b"<html>")
            with pytest.raises(ValueError):
                await sec.filing_document_head("https://evil.example/x.htm", 1000)

    asyncio.run(go())
