"""Calendario macro (FOMC + BLS) y resumen extractivo de 8-K. Red mockeada."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import (
    Base,
    Company,
    Document,
    DocumentChunk,
    Position,
    Tenant,
    WatchItem,
)
from app.services import macro_calendar_service as service
from app.services.connectors import macro_calendar as connector
from app.services.eight_k_digest import (
    eight_k_digest,
    is_material,
    summarize_items,
)

FOMC_HTML = """
<div class="panel-heading"><h4><a id="1">2026 FOMC Meetings</a></h4></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month col"><strong>January</strong></div>
<div class="fomc-meeting__date col">27-28</div></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month col"><strong>March</strong></div>
<div class="fomc-meeting__date col">17-18*</div></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month col"><strong>December</strong></div>
<div class="fomc-meeting__date col">8-9*</div></div>
<div class="panel-heading"><h4><a id="2">2025 FOMC Meetings</a></h4></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month col"><strong>Apr/May</strong></div>
<div class="fomc-meeting__date col">30-1</div></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month col"><strong>August</strong></div>
<div class="fomc-meeting__date col">22 (notation vote)</div></div>
"""

BLS_ICS = (
    "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART;TZID=US-Eastern:20261014T083000\r\n"
    "SUMMARY:Consumer Price Index\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART;TZID=US-Eastern:20261102T100000\r\n"
    "SUMMARY:Real Earnings\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART;TZID=US-Eastern:20261106T083000\r\n"
    "SUMMARY:Employment \r\n Situation\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


def run(coro):
    return asyncio.run(coro)


def test_parse_fomc_uses_last_day_and_skips_notation_votes() -> None:
    events = connector.parse_fomc_html(FOMC_HTML)
    assert [(e["start_date"], e["date"], e["projections"]) for e in events] == [
        ("2026-01-27", "2026-01-28", False),
        ("2026-03-17", "2026-03-18", True),
        ("2026-12-08", "2026-12-09", True),
        ("2025-04-30", "2025-05-01", False),
    ]


def test_parse_fomc_garbage_gives_empty() -> None:
    assert connector.parse_fomc_html("<html>cambio de formato</html>") == []


def test_parse_bls_unfolds_lines_and_keeps_time() -> None:
    events = connector.parse_bls_ics(BLS_ICS)
    assert {"title": "Employment Situation", "date": "2026-11-06", "time_et": "08:30"} in events
    assert len(events) == 3


def _transport(fomc_status=200, bls_body=BLS_ICS):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.federalreserve.gov":
            return httpx.Response(fomc_status, text=FOMC_HTML)
        return httpx.Response(200, text=bls_body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_macro_events_filtered_sorted_and_sourced() -> None:
    async def go():
        async with _transport() as client:
            return await service.get_macro_events(date(2026, 1, 1), date(2026, 11, 6), client=client)
    result = run(go())
    assert result["status"] == "ready"
    assert [e["date"] for e in result["events"]] == [
        "2026-01-28", "2026-03-18", "2026-10-14", "2026-11-06"]
    # Real Earnings no es de alto impacto: fuera.
    assert {e["kind"] for e in result["events"]} == {"fomc", "cpi", "employment"}
    for event in result["events"]:
        assert event["label"] == "OFICIAL" and event["source_url"].startswith("https://")


def test_macro_events_partial_when_one_source_fails() -> None:
    async def go():
        async with _transport(bls_body="<html>Access Denied</html>") as client:
            return await service.get_macro_events(date(2026, 1, 1), date(2026, 11, 6), client=client)
    result = run(go())
    assert result["status"] == "partial"
    assert {e["kind"] for e in result["events"]} == {"fomc"}
    assert [s["status"] for s in result["sources"]] == ["ready", "unavailable"]


def test_macro_events_unavailable_never_invents() -> None:
    async def go():
        async with _transport(fomc_status=503, bls_body="x") as client:
            return await service.get_macro_events(date(2026, 1, 1), date(2026, 2, 1), client=client)
    result = run(go())
    assert result["status"] == "unavailable" and result["events"] == []


def test_macro_events_rejects_bad_ranges() -> None:
    with pytest.raises(ValueError):
        run(service.get_macro_events(date(2026, 2, 1), date(2026, 1, 1)))
    with pytest.raises(ValueError):
        run(service.get_macro_events(date(2026, 1, 1), date(2028, 1, 1)))


EIGHT_K = """Item 2.02 Results of Operations and Financial Condition.
On October 1, 2026 the company announced revenue of $4.87 billion for the third quarter.
Forward-looking statements are subject to risks and uncertainties described elsewhere.
Item 5.02 Departure of Directors or Certain Officers.
The Board accepted the resignation of the Chief Financial Officer effective November 30, 2026.
Item 9.01 Financial Statements and Exhibits.
Exhibit 99.1 Press release dated October 1, 2026 issued by the company.
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act the registrant has duly caused this report."""


def test_summarize_items_extracts_literal_quotes_with_chunk_ids() -> None:
    items = summarize_items([{"id": 7, "chunk_index": 0, "text": EIGHT_K}])
    assert [i["code"] for i in items] == ["2.02", "5.02", "9.01"]
    assert items[0]["title"] == "Resultados de operaciones y situación financiera"
    assert items[0]["excerpts"] == [{
        "text": "On October 1, 2026 the company announced revenue of $4.87 billion for the third quarter.",
        "chunk_id": 7}]
    assert items[1]["excerpts"][0]["text"].startswith("The Board accepted")
    assert items[2]["excerpts"] == []


REAL_NVDA = """Item 2.02 Results of Operations and Financial Condition.
On August 27, 2025, NVIDIA announced financial results; see the quote from Colette M. Kress, NVIDIA's Executive Vice President and Chief Financial Officer, in the press release.
Item 5.02
Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers.
The Board announced that Ajay K. Puri, Executive Vice President of Worldwide Field Operations, will retire effective January 2026.
Item 7.01 Regulation FD Disclosure.
Statements made by NVIDIA with the U.S. Securities and Exchange Commission are available on its website.
Item 8.01 Other Events.
NVIDIA expanded its U.S. Government contracts program during the quarter to include new customers.
"""


def test_quotes_never_start_mid_sentence_on_initials_or_us() -> None:
    items = {i["code"]: i for i in summarize_items([{"id": 3, "chunk_index": 0, "text": REAL_NVDA}])}
    assert "Colette M. Kress" in items["2.02"]["excerpts"][0]["text"]
    assert "Ajay K. Puri" in items["5.02"]["excerpts"][0]["text"]
    assert items["5.02"]["excerpts"][0]["text"].startswith("The Board")
    assert "U.S. Government contracts" in items["8.01"]["excerpts"][0]["text"]
    for item in items.values():
        for excerpt in item["excerpts"]:
            assert excerpt["text"][0].isupper()
            assert not excerpt["text"].startswith("Securities and Exchange")


def test_official_title_on_next_line_is_not_an_excerpt() -> None:
    items = {i["code"]: i for i in summarize_items([{"id": 3, "chunk_index": 0, "text": REAL_NVDA}])}
    assert items["5.02"]["official_title"].startswith("Departure of Directors or Certain Officers;")
    assert all(not e["text"].startswith("Departure of Directors") for e in items["5.02"]["excerpts"])
    assert len(items["5.02"]["excerpts"]) == 1


def test_macro_range_beyond_source_calendar_is_partial() -> None:
    async def go():
        async with _transport() as client:
            return await service.get_macro_events(date(2026, 10, 1), date(2027, 9, 30), client=client)
    result = run(go())
    bls = next(s for s in result["sources"] if s["name"] == "BLS")
    assert bls["status"] == "partial" and bls["covered_until"] is not None
    assert result["status"] == "partial"


def test_is_material_ignores_exhibit_only_filings() -> None:
    assert not is_material([{"code": "9.01"}, {"code": "7.01"}])
    assert is_material([{"code": "9.01"}, {"code": "1.01"}])


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        tenant = Tenant(external_id="k-one", name="One")
        other = Tenant(external_id="k-two", name="Two")
        held = Company(ticker="HELD", name="Held Inc", exchange="NASDAQ", currency="USD",
                       company_type="holding", valuation_model="unassigned")
        stranger = Company(ticker="NOPE", name="Not Tracked", exchange="NASDAQ", currency="USD",
                           company_type="holding", valuation_model="unassigned")
        session.add_all([tenant, other, held, stranger])
        session.flush()
        session.info.update(tenant_id=tenant.id, held=held.id, stranger=stranger.id, other=other.id)
        session.add(Position(company_id=held.id, quantity=5, average_cost=1))
        session.commit()
        yield session
    engine.dispose()


def _filing(db, *, company, tenant=None, number=1, text=EIGHT_K, url=None, form="8-K"):
    doc = Document(
        tenant_id=tenant or db.info["tenant_id"], company_id=company, title="8-K",
        source_type="SEC",
        source_url=url or f"https://www.sec.gov/Archives/edgar/data/1/{number}/a.htm",
        checksum=f"h{number}", published_at=datetime(2026, 10, number, tzinfo=UTC),
        metadata_={"form": form})
    db.add(doc)
    db.flush()
    if text:
        db.add(DocumentChunk(tenant_id=doc.tenant_id, document_id=doc.id, chunk_index=0, text=text))
    db.commit()
    return doc


def test_digest_only_tracked_company_official_url_and_tenant(db) -> None:
    _filing(db, company=db.info["held"], number=3)
    _filing(db, company=db.info["stranger"], number=4)
    _filing(db, company=db.info["held"], number=5, url="https://evil.example/8k.htm")
    _filing(db, company=db.info["held"], number=6, form="10-K")
    result = eight_k_digest(db)
    assert result["total"] == 1
    entry = result["items"][0]
    assert entry["ticker"] == "HELD" and entry["matching"] == ["cartera"]
    assert entry["label"] == "OFICIAL" and entry["filed_at"] == "2026-10-03"
    assert entry["source_url"].startswith("https://www.sec.gov/")
    assert [i["code"] for i in entry["items"]] == ["2.02", "5.02", "9.01"]


def test_digest_without_text_is_insufficient_not_invented(db) -> None:
    _filing(db, company=db.info["held"], text="")
    entry = eight_k_digest(db)["items"][0]
    assert entry["status"] == "insufficient_data" and entry["items"] == []


def test_digest_derives_filed_at_from_filing_name(db) -> None:
    """QA 10: sin published_at, la fecha sale del nombre del filing."""
    doc = _filing(
        db,
        company=db.info["held"],
        number=7,
        url="https://www.sec.gov/Archives/edgar/data/19617/000095010326013842/jpm-20261013.htm",
    )
    doc.published_at = None
    db.commit()
    entry = eight_k_digest(db)["items"][0]
    assert entry["filed_at"] == "2026-10-13"


def test_digest_without_any_date_keeps_none_not_invented(db) -> None:
    doc = _filing(db, company=db.info["held"], number=8)
    doc.published_at = None
    db.commit()
    entry = eight_k_digest(db)["items"][0]
    assert entry["filed_at"] is None


def test_digest_rejects_invalid_filename_dates(db) -> None:
    doc = _filing(
        db,
        company=db.info["held"],
        number=9,
        url="https://www.sec.gov/Archives/edgar/data/1/9/x-20260230.htm",
    )
    doc.published_at = None
    db.commit()
    entry = eight_k_digest(db)["items"][0]
    assert entry["filed_at"] is None


def test_digest_paginates_and_other_tenant_is_invisible(db) -> None:
    for n in range(1, 6):
        _filing(db, company=db.info["held"], number=n)
    mine = db.info["tenant_id"]
    db.info["tenant_id"] = db.info["other"]
    _filing(db, company=db.info["held"], tenant=db.info["other"], number=9)
    db.info["tenant_id"] = mine
    first = eight_k_digest(db, page=1, page_size=2)
    last = eight_k_digest(db, page=3, page_size=2)
    assert first["total"] == 5 and len(first["items"]) == 2 and len(last["items"]) == 1
    assert first["items"][0]["filed_at"] == "2026-10-05"


def test_digest_watchlist_matching(db) -> None:
    db.add(WatchItem(symbol="NOPE"))
    db.commit()
    _filing(db, company=db.info["stranger"], number=2)
    assert eight_k_digest(db)["items"][0]["matching"] == ["watchlist"]


def test_digest_no_tracked_companies(db) -> None:
    db.query(Position).delete()
    db.commit()
    assert eight_k_digest(db)["status"] == "insufficient_data"


def test_digest_deduplicates_exact_sec_document_not_company(db) -> None:
    first = _filing(db, company=db.info["held"], number=2, text="")
    _filing(db, company=db.info["held"], number=3, url=first.source_url + "?output=1#section")
    _filing(db, company=db.info["held"], number=4)
    result = eight_k_digest(db)
    assert result["total"] == 2
    assert {item["filed_at"] for item in result["items"]} == {"2026-10-03", "2026-10-04"}


def test_digest_duplicate_empty_copy_does_not_hide_available_text(db) -> None:
    first = _filing(db, company=db.info["held"], number=2)
    _filing(db, company=db.info["held"], number=3, text="", url=first.source_url)
    result = eight_k_digest(db)
    assert result["total"] == 1
    assert result["items"][0]["status"] == "ready"
    assert result["items"][0]["items"][0]["excerpts"]
    assert result["items"][0]["document_id"] == first.id


def test_fuentes_se_consultan_en_paralelo(monkeypatch) -> None:
    """Perf: 479 ms medidos en el barrido 2026-10-31 (cache fria por worker).
    Las dos fuentes se pedian EN SERIE; en paralelo el total es el maximo
    de ambas, no la suma."""
    import time

    async def slow_fomc(agent, client):
        await asyncio.sleep(0.2)
        return connector.parse_fomc_html(FOMC_HTML)

    async def slow_bls(agent, client):
        await asyncio.sleep(0.2)
        return connector.parse_bls_ics(BLS_ICS)

    monkeypatch.setattr(connector, "fetch_fomc", slow_fomc)
    monkeypatch.setattr(connector, "fetch_bls", slow_bls)
    service.clear_cache()
    start = time.monotonic()
    result = run(service.get_macro_events(date(2026, 1, 1), date(2026, 10, 31)))
    elapsed = time.monotonic() - start
    assert result["status"] == "ready"
    # En serie: >= 0.40 s. En paralelo: ~0.20 s + epsilon.
    assert elapsed < 0.34, f"fuentes en serie: {elapsed:.2f}s para 2 x 0.20s"
