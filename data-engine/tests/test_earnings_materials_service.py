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

    async def cik_for_ticker(self, ticker, entity_name=None):
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


def test_cover_date_never_confirms_and_ended_context_wins():
    # Repro del auditor: portada de junio + trimestre cerrado en marzo NO es el T2.
    assert svc.check_period(
        "PRESS RELEASE June 5, 2026. Reports results for the quarter ended March 31, 2026.", "Jun/2026"
    ) == "contradice"
    # Una fecha suelta de portada/publicacion sin contexto no confirma nada.
    assert svc.check_period("PRESS RELEASE June 5, 2026. Results attached.", "Jun/2026") == "no_verificado"
    # Las comparativas de otros periodos no tumban una confirmacion real.
    assert svc.check_period(
        "results for the quarter ended June 30, 2026, compared with the quarter ended June 30, 2025", "Jun/2026"
    ) == "confirmado"
    # Solo periodo de otro año: contradice.
    assert svc.check_period("results for the quarter ended June 30, 2025", "Jun/2026") == "contradice"
    # Repro: la comparativa del año previo NO tumba el titular que confirma el trimestre.
    assert svc.check_period(
        "<h1>Second quarter 2026 results</h1><p>Revenue grew 12% compared with the quarter ended June 30, 2025.</p>",
        "Jun/2026",
    ) == "confirmado"
    # Un «ended» del MISMO año y otro mes es declaración estructurada de otro periodo:
    # contradice aunque el titular diga el trimestre del cierre.
    assert svc.check_period(
        "Second quarter 2026 results. Results for the quarter ended March 31, 2026.", "Jun/2026"
    ) == "contradice"


def test_quarter_mention_in_body_or_guidance_never_confirms():
    # Repro del auditor: titular T2-2025 + guía al T2-2026 en el cuerpo NO es Jun/2026.
    assert svc.check_period(
        "<h1>Second quarter 2025 results</h1><p>Guidance for second quarter 2026.</p>"
        "<p>Quarter ended June 30, 2025.</p>",
        "Jun/2026",
    ) == "contradice"
    # El trimestre del cierre solo en el cuerpo (sin «ended» del cierre) no confirma:
    # el titular es el periodo principal.
    assert svc.check_period(
        "<h1>Annual results 2025</h1><p>Strong momentum into second quarter 2026.</p>",
        "Jun/2026",
    ) == "no_verificado"
    # La guía en el propio titular tampoco confirma el periodo.
    assert svc.check_period(
        "<h1>Company raises guidance for second quarter 2026</h1><p>Details inside.</p>",
        "Jun/2026",
    ) == "no_verificado"
    # Pero el titular que SÍ informa del trimestre sigue confirmando aunque el
    # cuerpo compare con el año previo (pin del repro original).
    assert svc.check_period(
        "<h1>Second quarter 2026 results</h1><p>Revenue grew 12% compared with the quarter ended June 30, 2025.</p>",
        "Jun/2026",
    ) == "confirmado"
    # Texto plano sin marcas: solo el primer enunciado es el titular; el trimestre
    # del cierre en enunciados posteriores no confirma (repro del auditor).
    assert svc.check_period(
        "Second quarter 2025 results. Strong momentum into second quarter 2026. Quarter ended June 30, 2025.",
        "Jun/2026",
    ) == "contradice"
    # Y en texto plano el primer enunciado sigue confirmando (pins ya existentes).
    assert svc.check_period("Q2 2026 Update Highlights", "Jun/2026") == "confirmado"


def test_domestic_doc_with_cover_date_but_other_period_links_nothing():
    sec = FakeSEC(TSLA, {
        "0001628280-26-049213-index.htm": INDEX,
        "exhibit991.htm": "PRESS RELEASE July 22, 2026. Production update for the quarter ended March 31, 2026.",
        "deck.htm": "Highlights without any period",
    })
    assert _run(sec, date(2026, 7, 22))["status"] == "periodo_no_coincide"


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
    bn = {"filings": {"recent": {"form": ["6-K", "40-F"], "items": ["", ""], "filingDate": ["2026-08-10", "2026-03-01"],
                                 "accessionNumber": ["a", "b"]}}}
    assert _run(FakeSEC(bn), date(2026, 8, 13))["status"] == "sin_cobertura_sec"
    assert _run(FakeSEC(None, cik=None), date(2026, 8, 13))["status"] == "sin_cobertura_sec"


BN_6K = {
    "filings": {
        "recent": {
            "form": ["6-K", "6-K/A", "6-K"],
            "items": ["", "", ""],
            "filingDate": ["2026-08-13", "2026-08-13", "2026-05-10"],
            "accessionNumber": ["0009999999-26-000001", "0009999999-26-000002", "0009999999-26-000003"],
        }
    }
}
INDEX_6K = (
    "<table>"
    "<tr><td>1</td><td>6-K</td><td><a href='/x'>cover.htm</a> iXBRL</td><td>6-K</td></tr>"
    "<tr><td>2</td><td>EX-99.1</td><td><a href='/x'>release.htm</a></td><td>EX-99.1</td></tr>"
    "</table>"
)


def _run_6k(sec, event_date, label="Jun/2026"):
    return asyncio.run(
        svc.resolve_materials(sec=sec, ticker="BN", event_date=event_date, fiscal_label=label, confirmed=True)
    )


def test_foreign_issuer_6k_in_window_links_period_confirmed_docs():
    sec = FakeSEC(BN_6K, {
        "0009999999-26-000001-index.htm": INDEX_6K,
        "release.htm": "EX-99.1 PRESS RELEASE Brookfield Reports Second Quarter 2026 Results quarter ended June 30, 2026",
    })
    result = _run_6k(sec, date(2026, 8, 13))
    assert result["status"] == "ok" and result["filed_at"] == "2026-08-13"
    assert [(d["exhibit"], d["kind"]) for d in result["documents"]] == [("EX-99.1", "nota_prensa")]
    assert result["documents"][0]["url"] == (
        "https://www.sec.gov/Archives/edgar/data/1318605/000999999926000001/release.htm"
    )


def test_foreign_issuer_6k_amendment_loses_to_base_form_same_day():
    filing = svc.pick_results_filing(BN_6K, date(2026, 8, 13), forms=("6-K", "6-K/A"), require_results_item=False)
    assert filing["accession"] == "0009999999-26-000001" and filing["form"] == "6-K"
    only_amended = {"filings": {"recent": {"form": ["6-K/A"], "items": [""], "filingDate": ["2026-08-14"],
                                             "accessionNumber": ["0009999999-26-000009"]}}}
    filing = svc.pick_results_filing(only_amended, date(2026, 8, 13), forms=("6-K", "6-K/A"), require_results_item=False)
    assert filing["accession"] == "0009999999-26-000009" and filing["form"] == "6-K/A"


def test_foreign_issuer_without_6k_in_window_asserts_nothing():
    assert _run_6k(FakeSEC(BN_6K), date(2026, 6, 1))["status"] == "sin_cobertura_sec"


def test_foreign_issuer_6k_without_period_confirmation_links_nothing():
    sec = FakeSEC(BN_6K, {
        "0009999999-26-000001-index.htm": INDEX_6K,
        "release.htm": "Highlights with no date at all",
    })
    result = _run_6k(sec, date(2026, 8, 13))
    assert result["status"] == "sin_cobertura_sec" and result["documents"] == []


def test_foreign_issuer_unreadable_index_is_failure_not_absence():
    assert _run_6k(FakeSEC(BN_6K, {}), date(2026, 8, 13))["status"] == "no_disponible"


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
